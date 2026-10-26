"""Real signals, flock and supervisord, in a disposable Linux test environment.

Run on macOS with the rest of pytest (Linux cases skip), and in a Linux container
with procps/util-linux and tests/requirements.txt for the process-level proof.
"""
from __future__ import annotations

import configparser
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_helper():
    loader = importlib.machinery.SourceFileLoader("gateway_restart", str(ROOT / "files/feina-gateway-restart"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def until(check, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError("condition timed out")


FAKE_HERMES = r'''#!/usr/bin/env python3
import json, os, signal, time
from pathlib import Path
home = Path(os.environ['HERMES_HOME'])
start = int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19])
def term(sig, frame):
    with (home / 'term.log').open('a') as stream:
        stream.write(str(os.getpid()) + '\n')
    if not (home / 'stubborn').exists():
        raise SystemExit(0)
signal.signal(signal.SIGTERM, term)
while True:
    draining = (home / '.drain_request.json').exists()
    active = int((home / 'active').read_text()) if (home / 'active').exists() else 0
    if draining and (home / 'race').exists():
        active = 1
    body = {'pid': os.getpid(), 'start_time': start, 'active_agents': active,
            'gateway_state': 'draining' if draining else 'running'}
    temp = home / ('status.' + str(os.getpid()))
    temp.write_text(json.dumps(body))
    temp.replace(home / 'gateway_state.json')
    time.sleep(0.02)
'''


@pytest.fixture
def gateway(tmp_path, monkeypatch, request):
    if sys.platform != "linux":
        pytest.skip("real gateway process proof requires Linux /proc and flock")
    pytest.importorskip("supervisor")
    assert shutil.which("flock") and shutil.which("pgrep"), "install util-linux and procps"
    mod = load_helper()
    mod.HOME = home = tmp_path / "home/.hermes"
    mod.STATE = state = tmp_path / "state"
    mod.WAIT = 2.0
    home.mkdir(parents=True)
    state.mkdir()
    (home / "config.yaml").touch()
    (home / "auth.json").write_text('{}')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(FAKE_HERMES)
    hermes.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    wrapper = tmp_path / "gateway-run.sh"
    source = (ROOT / "files/gateway-run.sh").read_text()
    # Only relocate the fixed VM filesystem layout; keep production lock/exec logic.
    source = source.replace('/root', str(tmp_path / 'home')).replace('/var/lib/orgo', str(state))
    mod.current_wrapper_source = source
    legacy = getattr(request, "param", "current") == "legacy"
    if legacy:
        source = source[:source.index('# Inherit the lock')] + (
            'exec flock ' + str(state / 'hermes-gateway.lock') + ' hermes gateway run --replace --accept-hooks\n')
    wrapper.write_text(source)
    wrapper.chmod(0o755)
    conf = tmp_path / "supervisor.conf"
    conf.write_text(f'''[unix_http_server]
file={tmp_path}/supervisor.sock
[supervisord]
logfile={tmp_path}/supervisord.log
pidfile={tmp_path}/supervisord.pid
childlogdir={tmp_path}
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix://{tmp_path}/supervisor.sock
[program:hermes-gateway]
command={wrapper}
autostart=true
autorestart=true
startsecs=0
stopsignal=TERM
stopwaitsecs=1
stopasgroup={'false' if legacy else 'true'}
killasgroup={'false' if legacy else 'true'}
stdout_logfile={tmp_path}/gateway.log
stderr_logfile={tmp_path}/gateway.err
''')
    ctl = bin_dir / "supervisorctl"
    ctl.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m supervisor.supervisorctl -c "{conf}" "$@"\n')
    ctl.chmod(0o755)
    server = subprocess.Popen([sys.executable, "-m", "supervisor.supervisord", "-n", "-c", str(conf)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        until(lambda: (home / "gateway_state.json").exists())
        old = mod.gateways()
        assert len(old) == 1
        yield mod, wrapper, old[0]
    finally:
        subprocess.run([str(ctl), "shutdown"], capture_output=True, timeout=10)
        server.wait(timeout=10)
        # Legacy tests intentionally create an orphan; only kill identities captured here.
        for proc in mod.gateways():
            try:
                argv = Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(b"\0")
            except FileNotFoundError:
                continue
            if os.fsencode(hermes) in argv:
                mod.signal_old(proc, signal.SIGKILL)


def test_restart_delivers_term_changes_pid_and_preserves_exclusivity(gateway):
    mod, wrapper, old = gateway
    assert mod.supervisor("pid", "hermes-gateway") == str(old.pid)
    started = time.monotonic()
    second = subprocess.run([str(wrapper)], capture_output=True, text=True, timeout=2)
    assert second.returncode != 0 and 'gateway already running' in second.stderr
    assert time.monotonic() - started < 2
    mod.restart()
    current = mod.gateways()
    assert len(current) == 1 and current[0].pid != old.pid
    assert mod.process(old.pid) is None
    assert str(old.pid) in (mod.HOME / "term.log").read_text().splitlines()
    assert not (mod.HOME / ".drain_request.json").exists()


@pytest.mark.parametrize("reason", ["active", "unknown", "race", "existing-drain"])
def test_busy_unknown_or_racing_turn_is_not_stopped(gateway, monkeypatch, reason):
    mod, _, old = gateway
    if reason == "active":
        (mod.HOME / 'active').write_text('1')
        until(lambda: json.loads((mod.HOME / 'gateway_state.json').read_text())['active_agents'] == 1)
    elif reason == "unknown":
        original = Path.read_text
        def unreadable(path, *args, **kwargs):
            if path == mod.HOME / 'gateway_state.json':
                raise PermissionError("test unreadable state")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'read_text', unreadable)
    elif reason == "race":
        (mod.HOME / 'race').touch()
    else:
        (mod.HOME / '.drain_request.json').write_text('{"principal":"other-operator"}')
    with pytest.raises((mod.Refused, FileExistsError)):
        mod.restart()
    assert mod.gateways() == [old]
    assert not (mod.HOME / 'term.log').exists()
    if reason == 'existing-drain':
        assert json.loads((mod.HOME / '.drain_request.json').read_text())['principal'] == 'other-operator'
    else:
        assert not (mod.HOME / '.drain_request.json').exists()


@pytest.mark.parametrize("gateway", ["legacy"], indirect=True)
@pytest.mark.parametrize("stubborn", [False, True])
def test_recovers_legacy_flock_orphan_term_before_kill(gateway, monkeypatch, stubborn):
    mod, wrapper, old = gateway
    wrapper.write_text(mod.current_wrapper_source)
    assert mod.supervisor('pid', 'hermes-gateway') != str(old.pid)
    if stubborn:
        (mod.HOME / 'stubborn').touch()
    delivered = []
    real = mod.signal_old
    def record(proc, sig):
        delivered.append(sig)
        real(proc, sig)
    monkeypatch.setattr(mod, 'signal_old', record)
    mod.restart()
    assert delivered == ([signal.SIGTERM, signal.SIGKILL] if stubborn else [signal.SIGTERM])
    assert len(mod.gateways()) == 1 and mod.gateways()[0].pid != old.pid
    assert str(old.pid) in (mod.HOME / 'term.log').read_text().splitlines()


def test_duplicate_gateway_is_refused_without_signals(gateway):
    mod, wrapper, old = gateway
    other_home = mod.HOME.parent / 'other-hermes'
    other_home.mkdir()
    fake = wrapper.parent / 'bin/hermes'
    extra = subprocess.Popen([str(fake), 'gateway', 'run'],
                             env={**os.environ, 'HERMES_HOME': str(other_home)}, start_new_session=True)
    try:
        until(lambda: len(mod.gateways()) == 2)
        with pytest.raises(mod.Refused, match='multiple gateways'):
            mod.restart()
        assert mod.process(old.pid) == old
        assert not (mod.HOME / 'term.log').exists()
    finally:
        extra.terminate()
        extra.wait(timeout=5)


def test_failed_replacement_is_reported(gateway):
    mod, wrapper, old = gateway
    wrapper.write_text('#!/bin/sh\nexit 23\n')
    with pytest.raises(mod.Refused):
        mod.restart()
    assert mod.process(old.pid) is None
    assert not mod.gateways()
    assert not (mod.HOME / '.drain_request.json').exists()


def test_parallel_restart_is_refused_without_stopping(gateway, monkeypatch):
    import fcntl
    mod, _, old = gateway
    monkeypatch.setattr(sys, 'argv', ['feina-gateway-restart'])
    with (mod.STATE / 'hermes-gateway-restart.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert mod.main() == 1
    assert mod.gateways() == [old]
    assert not (mod.HOME / 'term.log').exists()


def test_bootstrap_shutdown_settings_preserve_other_unit_options(tmp_path):
    source = (ROOT / 'files/bootstrap.sh').read_text()
    conf = tmp_path / 'gateway.conf'
    conf.write_text('[program:hermes-gateway]\ncommand=/custom/wrapper\nstdout_logfile=/custom/log\n')
    snippet = source.split("python3 - <<'PYUNIT'\n", 1)[1].split('\nPYUNIT', 1)[0]
    subprocess.run([sys.executable, '-c', snippet.replace('/etc/supervisor/conf.d/hermes-gateway.conf', str(conf))], check=True)
    cfg = configparser.RawConfigParser()
    cfg.read(conf)
    section = cfg['program:hermes-gateway']
    assert section['command'] == '/custom/wrapper'
    assert section['stdout_logfile'] == '/custom/log'
    assert section['stopsignal'] == 'TERM' and section['stopwaitsecs'] == '30'
    assert section['stopasgroup'] == 'true' and section['killasgroup'] == 'true'


def test_no_direct_supervisor_restart_callers_remain():
    paths = [ROOT / 'files', ROOT / 'docs', ROOT / 'build_template.py']
    for root in paths:
        for path in root.rglob('*') if root.is_dir() else [root]:
            if path.is_file() and (path.suffix in {'.sh', '.py', '.md'} or path.name == 'feina-gateway-restart'):
                assert 'supervisorctl restart hermes-gateway' not in path.read_text(), path
