# feina-stack

**Feina's base image for client AI agents** — a trimmed fork of [Nick Vasilescu's MIT-licensed nicks-stack](https://github.com/nickvasilescu/nicks-stack) (v0.2.2). Each small-business client gets a dedicated cloud computer, their own Telegram bot, and isolated secrets. Clients only ever chat on Telegram; Feina operates the infrastructure from outside.

Hermes is pinned to **v0.21.7** (`71d34bad1045610252eda02ee79549436896e784`).

## What ships (Basic)

| Piece | Role |
|--------|------|
| Hermes gateway | Supervised agent (auto-restart) |
| Model | **openai-codex** (ChatGPT OAuth device code) — **no OpenAI API key** on the VM |
| Telegram | Bot token installed by Feina (`feina-onboard telegram`); client allowlisted after Start |
| Composio | Client's Gmail, Calendar, Sheets — connected **in-meeting**; key pasted by Feina only |
| AgentMail | Agent inbox for CSVs / invoices |
| Honcho memory | Default provider when `HONCHO_API_KEY` is set (fail-open without key) |
| Notes vault | Markdown vault at `/root/Documents/HermesVault` |
| Latitude | Optional tracing |
| 1Password | Optional per-client vault (`Feina - <Client>`) |
| Persona | Calm chief-of-staff; **approvals on** — full draft + explicit yes before any send |

## On by default (Basic)

Composio MCP (key added in-meeting), AgentMail, Latitude, notes vault, and **Honcho memory** (`memory.provider: honcho` when `HONCHO_API_KEY` is present). Keys land via Feina pre-setup (`feina-onboard op-token` / individual commands). **Linear** MCP stays **off** unless you `feina enable linear`.

## v1.0 onboarding (two phases)

Run `feina-onboard setup` on the VM for the full checklist.

### A) Feina pre-setup (before the client meeting)

1. Bootstrap the VM (`ops/launch-client.sh` or manual `bootstrap.sh`).
2. **ChatGPT** — Feina completes OAuth (no API key): `feina-onboard model-codex`.
3. **Telegram** — Feina creates the bot in BotFather, then `feina-onboard telegram <token>`; `feina-onboard gateway-test`.
4. **Honcho, AgentMail, Latitude** — Feina sets keys (`op-token` or `honcho` / `agentmail` / `latitude`).
5. **`feina-onboard safety-check`** before the call.

### B) In-meeting (client)

1. Client creates **their own Composio** account and connects apps in Composio's UI.
2. Client gives Feina the Composio key → Feina runs `feina-onboard composio <key>` (client never touches the VM).
3. Client taps **Start** in Telegram → Feina runs `pending-telegram` then `allow-telegram <user_id>`.
4. Client sends a test message.

## Installed but off by default

AgentPhone, AgentCard, vidIQ, X, IdeaBrowser, Spotify, alternate model providers, etc. — `feina enable <name>`.

## Blocked on clients

- Orgo fleet control (`feina enable orgo` refused); `ORGO_*` stripped from `.env`.
- Computer-use skills document **Feina ops only** workflows.

## Launch a new client (ops)

Requires an **account-wide** `ORGO_API_KEY` on your ops machine. For Honcho isolation, also set **`FEINA_HONCHO_ADMIN_KEY`** (Honcho admin key — **never** on client VMs).

```bash
export ORGO_API_KEY=sk_live_...
export FEINA_HONCHO_ADMIN_KEY=...   # Honcho admin; ops only
./ops/launch-client.sh <workspace_id> <slug> 8 2
```

**Phased, resumable launch** (`ops/feina_launch.py` via `launch-client.sh`):

| Phase | What | State |
|-------|------|--------|
| **A** | Honcho workspace + scoped key (no Orgo computer) | `~/.feina/clients/<slug>/` |
| **B** | Orgo `/account/capacity` preflight | exit **2** if no slot (Phase A kept) |
| **C** | Create VM, bootstrap, `push-config` Honcho | `launch.json` tracks `computer_id` |

Re-run skips completed phases. If there is no free slot:

`Unable to create the new Orgo computer for <slug>: no free slot. Buy or free a computer in Orgo, then re-run.`

The launcher does **not** auto-purchase or upgrade Orgo capacity.

**Day before the meeting:** `ops/ready-check.sh <slug>` — pass/fail checklist (VM running, bootstrap, Codex auth, Telegram/gateway, Honcho workspace, AgentMail/Latitude, safety-check, no Orgo/OpenAI API keys on the client).

### Honcho per-client isolation

Honcho v3 uses **workspaces** as hard isolation boundaries ([architecture](https://honcho.dev/docs/v3/documentation/core-concepts/architecture)).

**Memory derivation vs storage:** Peers, sessions, and message **storage** (plus workspace isolation) work with a workspace-scoped key alone. **Representation / chat-style derived memory** (deriver queue) also needs Honcho **credits** and instance setup on the Honcho side — without it, ingestion works but conclusions/representation can lag. `ops/ready-check.sh` warns when the deriver queue is not draining.

On launch, `ops/feina_honcho.py provision --slug <slug>`:

1. **Get-or-creates** workspace `feina-<slug>` (`POST /v3/workspaces`).
2. Mints a **workspace-scoped API key** (`POST /v3/keys?workspace_id=...`) so the client VM cannot read other clients' memory.
3. Stores ops state under `~/.feina/clients/<slug>/honcho.json` (mode `600`).

Copy the **workspace-scoped** key into the client's 1Password `HONCHO_API_KEY` field. After bootstrap:

```bash
python3 ops/feina_honcho.py push-config --slug <slug> --computer-id <computer_id>
```

This writes `~/.hermes/honcho.json` (workspace + peers) and `HONCHO_API_KEY` / `HONCHO_WORKSPACE_ID` on the VM.

**Offboard:** export client Honcho memory first, then teardown (required unless `--honcho-force`):

```bash
ops/offboard-client.sh <computer_id> --slug <slug> \
  --honcho-export /tmp/honcho-<slug>-memory.json --honcho-teardown
```

`feina_honcho.py teardown` exports session-scoped messages, deletes sessions/workspace, and polls `POST /v3/workspaces/list` until the workspace id is gone (async `DELETE` returns 202). Local `honcho.json` is removed only after that confirmation. **No** secrets in the archive.

**Limitations:** Honcho Cloud does not expose workspace `GET` or programmatic key revoke/list/delete (405) — workspace presence is checked via `workspaces/list` only. After teardown, **revoke the scoped client key manually** in [Honcho → API Keys](https://app.honcho.dev/api-keys). Feina's **admin** key must remain on ops only.

Then on the VM (pre-setup):

```bash
feina-onboard setup-pre
# … model-codex, telegram, secrets, safety-check
```

## Client reliability parts (template v1.1.1)

Membr download, the login check and one re-run, Telegram background jobs, proactive starters, and the no-LLM evals ship in the image and stay off. Turning a part on for a client computer is a separate step that a person approves. See [docs/INSTALL-v1.1.0.md](docs/INSTALL-v1.1.0.md) and [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Build the Orgo template (Scale plan)

```bash
python3 build_template.py
# VERSION defaults to 1.1.1. --build needs ORGO_API_KEY and is not a client install.
```

## Credit

Forked from **Nick Vasilescu's [nicks-stack](https://github.com/nickvasilescu/nicks-stack)** (MIT). See [LICENSE](LICENSE).

## Untested in CI

Full VM smoke: bootstrap, codex OAuth, Telegram token + allow-telegram, Composio in-meeting, `safety-check`, Honcho fail-open.
