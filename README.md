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

Requires an **account-wide** `ORGO_API_KEY` on your ops machine.

```bash
export ORGO_API_KEY=sk_live_...
./ops/launch-client.sh <workspace_id> <slug> 8 2
```

The script **lists workspace computers and account capacity** first. If there is no free slot it exits with **`needs human approval: no free slot`** — it does **not** auto-purchase or upgrade Orgo capacity.

Then on the VM (pre-setup):

```bash
feina-onboard setup-pre
# … model-codex, telegram, secrets, safety-check
```

## Build the Orgo template (Scale plan)

```bash
python3 build_template.py
VERSION=1.0.0 python3 build_template.py --build   # needs ORGO_API_KEY + Scale
```

## Credit

Forked from **Nick Vasilescu's [nicks-stack](https://github.com/nickvasilescu/nicks-stack)** (MIT). See [LICENSE](LICENSE).

## Untested in CI

Full VM smoke: bootstrap, codex OAuth, Telegram token + allow-telegram, Composio in-meeting, `safety-check`, Honcho fail-open.
