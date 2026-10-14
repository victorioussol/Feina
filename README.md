# feina-stack

**Feina's base image for client AI agents** — a trimmed fork of [Nick Vasilescu's MIT-licensed nicks-stack](https://github.com/nickvasilescu/nicks-stack) (v0.2.2). Each small-business client gets a dedicated cloud computer, their own Telegram bot, and isolated secrets. Clients only ever chat on Telegram; Feina operates the infrastructure from outside.

Hermes is pinned to **v0.21.7** (`71d34bad1045610252eda02ee79549436896e784`).

## What ships (Basic)

| Piece | Role |
|--------|------|
| Hermes gateway | Supervised agent (auto-restart) |
| Model | **openai-codex** (ChatGPT OAuth) or **OpenRouter** with key only |
| Telegram | QR bot creation (`feina-onboard telegram-qr`), BotFather fallback |
| Composio | Client's Gmail, Calendar, Sheets, etc. |
| AgentMail | Agent inbox for CSVs / invoices |
| Notes vault | Markdown vault at `/root/Documents/HermesVault` via `mcp-server-filesystem` (installed binary, not `npx` at runtime) |
| Latitude | Optional tracing (no-op until keys set); core patch is non-fatal |
| 1Password | Optional per-client vault (`Feina - <Client>`) |
| Persona | Calm chief-of-staff; **approvals on** before send/delete/spend |

## Explicitly removed (vs Nick's stack)

Orgo MCP and desktop-control plugin, AgentPhone, AgentCard, X/Linear/ideabrowser/vidiq, Nous as default model, desktop onboarding UI, wallpaper autostart, and related skills. **No `ORGO_*` keys** may exist on client machines.

Industry skills are **not** baked in — use `files/skills/client-drop/` (see README there).

## Launch a new client

Plain-language flow for Feina ops (not the client):

1. **Prepare secrets** (1Password vault `Feina - <Client>`, optional OpenRouter cap, AgentMail inbox, Composio/Latitude when ready). Never put the Orgo API key on the client VM.
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
4. **Model** — ChatGPT account Feina owns for the client:
   ```bash
   feina-onboard model-codex    # copy URL + device code; sign in at chatgpt.com
   ```
   Or OpenRouter only:
   ```bash
   feina-onboard model-openrouter 'sk-or-...'
   ```
5. **Telegram** — Feina's Telegram account scans the QR (expires in minutes):
   ```bash
   export FEINA_BOT_NAME="Vince · Feina"
   feina-onboard telegram-qr
   # PNG: /root/telegram_qr.png — add client later:
   feina-onboard allow-user <telegram_user_id>
   ```
6. **Keys** — `feina-onboard composio …`, `agentmail …`, `latitude …`, `op-token …` as needed.
7. **Industry pack** — copy skills into `/root/.hermes/skills/client-drop/` and seed vault notes.
8. **Verify** — `feina-onboard status` (gateway running, Hermes 0.21.7, MCP list without orgo/x/linear, no ORGO keys).

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

No Orgo build was run from CI here. Before Vince's launch, verify on a real VM: full bootstrap log, `hermes --version` = 0.21.7, Telegram connect, codex OAuth, OpenRouter-only boot, Latitude plugin with patch skipped, and `feina-onboard status` clean.
