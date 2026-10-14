# feina-stack

**Feina's base image for client AI agents** — a trimmed fork of [Nick Vasilescu's MIT-licensed nicks-stack](https://github.com/nickvasilescu/nicks-stack) (v0.2.2). Each small-business client gets a dedicated cloud computer, their own Telegram bot, and isolated secrets. Clients only ever chat on Telegram; Feina operates the infrastructure from outside.

Hermes is pinned to **v0.21.7** (`71d34bad1045610252eda02ee79549436896e784`).

## What ships (Basic)

| Piece | Role |
|--------|------|
| Hermes gateway | Supervised agent (auto-restart) |
| Model | **openai-codex** (ChatGPT OAuth) — **MVP default**; no fallback model |
| Telegram | QR bot creation (`feina-onboard telegram-qr`), BotFather fallback |
| Composio | Client's Gmail, Calendar, Sheets, etc. |
| AgentMail | Agent inbox for CSVs / invoices |
| Notes vault | Markdown vault at `/root/Documents/HermesVault` via `mcp-server-filesystem` (installed binary, not `npx` at runtime) |
| Latitude | Optional tracing (no-op until keys set); core patch is non-fatal |
| 1Password | Optional per-client vault (`Feina - <Client>`) |
| Persona | Calm chief-of-staff; **approvals on** — full draft + explicit yes before any send |

## On by default (Basic)

Composio, AgentMail, Latitude, notes vault MCP — enabled in config (keys still required at runtime).

## Installed but off by default (enable per client)

Packages, skills, and MCP entries are **present in the image** with `enabled: false` and empty keys until you turn them on:

| Integration | Enable |
|-------------|--------|
| AgentPhone (+ webhook bridge) | `feina enable agentphone` then set `AGENTPHONE_*` keys |
| AgentCard | `feina enable agentcard` |
| vidIQ, IdeaBrowser, Linear | `feina enable vidiq` / `ideabrowser` / `linear` |
| X (x-docs, xapi, xapi-app-only) | `feina enable x-docs` etc. |
| Spotify / xAI plugins | `feina enable spotify` / `xai` |
| OpenRouter / Anthropic / Vercel gateway / Meta API | `feina enable openrouter` / `anthropic` (add keys first) |

List state: `feina list`. Setup keys: `feina-onboard …`.

## Removed or blocked (security / product)

- **Orgo control on clients:** `orgo` MCP and `orgo-desktop-local` plugin stay in the tree but **`feina enable orgo` is refused**; `ORGO_*` keys are stripped from `.env` and never bridged from the launch vault. Computer-use **skills** document ops workflows only.
- **Nous** and other non-codex defaults (MVP is ChatGPT sign-in only).
- Nick's aggressive persona and approvals-off (Feina SOUL + draft-and-yes approvals).
- Desktop onboarding UI, wallpaper autostart (headless client product).

Industry packs are **not** baked in — use `/root/.hermes/skills/client-drop/`.

## Launch a new client

Plain-language flow for Feina ops (not the client):

1. **Prepare secrets** (1Password vault `Feina - <Client>`, optional OpenRouter cap for later, AgentMail inbox, Composio/Latitude when ready). Never put the Orgo API key on the client VM.
2. **Create the computer** in Feina's Orgo workspace (medium 8 GB recommended for Chrome-heavy tools). From your ops machine:
   ```bash
   export ORGO_API_KEY=sk_live_...
   ./ops/launch-client.sh <workspace_id> <slug> 8 2
   ```
   Or create a blank VM and bootstrap manually (below).
3. **Bootstrap** (idempotent, ~35–50 min). On the new computer as root:
   ```bash
   export FEINA_STACK_REF=feina   # branch or tag
   mkdir -p /opt/feina-stack && git clone --depth 1 -b "$FEINA_STACK_REF" \
     https://github.com/victorioussol/Feina /opt/feina-stack/src
   nohup bash /opt/feina-stack/src/files/bootstrap.sh >> /var/log/feina-bootstrap.log 2>&1 &
   tail -f /var/log/feina-bootstrap.log   # wait for "feina-stack install complete"
   ```
   One-liner over curl (pinned ref):
   ```bash
   curl -fsSL "https://raw.githubusercontent.com/victorioussol/Feina/feina/files/bootstrap.sh" | bash
   ```
   *(The curl path only works after this branch is pushed; prefer git clone until then.)*
4. **Model (MVP)** — ChatGPT account Feina owns for the client:
   ```bash
   feina-onboard setup          # prints step list
   feina-onboard model-codex    # copy URL + device code; sign in at chatgpt.com
   ```
   Alternate models later: `feina enable openrouter` (or `anthropic`) after adding keys — not part of first-boot MVP.
5. **Telegram** — Feina's Telegram account scans the QR (expires in minutes):
   ```bash
   export FEINA_BOT_NAME="Vince · Feina"
   feina-onboard telegram-qr
   # PNG: /root/telegram_qr.png — add client later:
   feina-onboard allow-user <telegram_user_id>
   ```
   See skill `hermes-gateway-onboarding` → `references/telegram-managed-qr-onboarding.md`.
6. **Keys** — `feina-onboard composio …`, `agentmail …`, `latitude …`, `op-token …` as needed.
7. **Industry pack** — copy skills into `/root/.hermes/skills/client-drop/` and seed vault notes.
8. **Optional integrations** — `feina enable agentphone` (etc.), then add keys and restart checks via `feina-onboard status`.
9. **Verify** — `feina-onboard status` (Hermes 0.21.7, orgo MCP off, no `ORGO_*` in `.env`).

**Meeting day:** client connects Composio apps and sends a Telegram message; you `allow-user` their id.

**Offboard:** export vault, revoke keys, delete bot, then `./ops/offboard-client.sh <computer_id> --delete-computer`.

## Build the Orgo template (Scale plan)

```bash
python3 build_template.py              # assemble feina-stack.resolved.json + validate
VERSION=1.0.0 python3 build_template.py --build   # needs ORGO_API_KEY + Scale
```

Publishing templates requires Orgo Scale; until then use bootstrap on blank computers.

## Credit

Forked from **Nick Vasilescu's [nicks-stack](https://github.com/nickvasilescu/nicks-stack)** (MIT). See [LICENSE](LICENSE).

## Untested in this repo

No Orgo build was run from CI here. Before launch, verify on a real VM: full bootstrap log, `hermes --version` = 0.21.7, Telegram connect, ChatGPT (codex) OAuth, `feina-onboard status` clean, and optional `feina enable` paths as needed.
