#!/usr/bin/env python3
# feina-stack — Telegram managed-bot QR pairing (headless-friendly)
import argparse
import os
import sys
import time
import subprocess

QR_PATH = os.environ.get("FEINA_TELEGRAM_QR_PATH", "/root/telegram_qr.png")
DISPLAY = os.environ.get("DISPLAY", ":99")


def log(msg):
    print(f"[telegram-pair] {msg}", flush=True)


def render_qr_png(payload: str, path: str) -> bool:
    try:
        import qrcode
    except ImportError:
        log("qrcode not in venv; installing via uv…")
        for cmd in (
            ["uv", "pip", "install", "--python", sys.executable, "qrcode[pil]"],
            ["/root/.hermes/bin/uv", "pip", "install", "--python", sys.executable, "qrcode[pil]"],
            [sys.executable, "-m", "pip", "install", "qrcode[pil]"],
        ):
            if subprocess.run(cmd, check=False).returncode == 0:
                break
        try:
            import qrcode
        except ImportError:
            return False
    qrcode.make(payload).save(path)
    return True


def show_qr_on_desktop(path: str):
    env = dict(os.environ, DISPLAY=DISPLAY)
    for browser in ("google-chrome-stable", "google-chrome", "chromium"):
        try:
            subprocess.Popen(
                [
                    browser,
                    "--no-sandbox",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"file://{path}",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except FileNotFoundError:
            continue
    return False


def append_allowed_user(uid: str):
    from hermes_cli.config import save_env_value

    env_path = "/root/.hermes/.env"
    current = ""
    try:
        with open(env_path) as fh:
            for line in fh:
                if line.startswith("TELEGRAM_ALLOWED_USERS="):
                    current = line.split("=", 1)[1].strip()
    except OSError:
        pass
    ids = [x.strip() for x in current.split(",") if x.strip()]
    if uid not in ids:
        ids.append(uid)
        save_env_value("TELEGRAM_ALLOWED_USERS", ",".join(ids))
        log(f"Appended {uid} to TELEGRAM_ALLOWED_USERS → {','.join(ids)}")
    else:
        log(f"User {uid} already in allowlist")


def main():
    parser = argparse.ArgumentParser(description="Feina Telegram bot QR pairing")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Do not open Chrome; print deep link and save PNG only",
    )
    parser.add_argument(
        "--append-allowlist",
        action="store_true",
        help="On success, append owner id instead of replacing allowlist",
    )
    parser.add_argument("--bot-name", default=os.environ.get("FEINA_BOT_NAME", "Feina Assistant"))
    args = parser.parse_args()

    from hermes_cli.telegram_managed_bot import (
        create_pairing,
        poll_for_setup_result,
        render_qr_terminal,
    )
    from hermes_cli.config import save_env_value

    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        pairing = create_pairing(bot_name=args.bot_name)
        log("Pairing created. Deep link (open on phone):")
        print(pairing.deep_link, flush=True)
        if render_qr_png(pairing.qr_payload, QR_PATH):
            log(f"QR PNG saved: {QR_PATH}")
            if not args.headless:
                show_qr_on_desktop(QR_PATH)
        else:
            try:
                print(render_qr_terminal(pairing.qr_payload), flush=True)
            except Exception:
                pass
        log("Scan → Telegram → tap 'Create Bot'. Waiting up to 180s…")
        try:
            result = poll_for_setup_result(None, pairing, timeout=180, interval=2)
        except Exception as exc:
            log(f"Poll ended ({exc}); minting a fresh QR…")
            result = None
        if result and result.token:
            save_env_value("TELEGRAM_BOT_TOKEN", result.token)
            uid = str(result.owner_user_id)
            if args.append_allowlist:
                append_allowed_user(uid)
            else:
                save_env_value("TELEGRAM_ALLOWED_USERS", uid)
                save_env_value("TELEGRAM_HOME_CHANNEL", uid)
            if result.bot_username:
                save_env_value("TELEGRAM_BOT_USERNAME", result.bot_username)
            log(f"Paired! bot=@{result.bot_username}, owner={uid}")
            return 0
        log("No pairing yet — regenerating QR…")
    log("Timed out waiting for a Telegram pairing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
