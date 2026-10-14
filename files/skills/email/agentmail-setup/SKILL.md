---
name: agentmail-setup
description: Set up AgentMail direct and through Composio; diagnose send blocks, bounce suppression, and inbound vs outbound delivery failures.
version: 0.3.2
author: Hermes
metadata:
  hermes:
    tags: [AgentMail, Email, Composio, MCP, Outbound, Slack]
---

# AgentMail Setup

Set up AgentMail as an API-first email inbox provider for agents, either directly with AgentMail credentials/CLI/MCP or indirectly through Composio when a Composio-connected toolkit is available. This skill does not assume AgentMail is already connected in Composio; it verifies the available Composio surface first and uses exact tool slugs discovered at runtime. Dependency stance: use `terminal` for CLI/API checks and Hermes MCP configuration, and prefer environment variables over pasted secrets.

Also covers **operational delivery failures**: outbound 403 bounce suppression (`send/block`) and how that differs from missing **inbound** OTP/notices.

Covers **Feina outbound policy**: draft every email in chat (to, subject, body) and send only after the client's explicit yes (see `SOUL.md`).

## When to Use

- The user says “set up AgentMail,” “agentmail.to,” or “give the agent an email inbox.”
- The user wants agent-controlled inboxes for signups, OTP/2FA, support, scheduling, or email workflows.
- The user mentions Composio access to AgentMail or asks whether AgentMail can be routed through Composio.
- You need to add AgentMail as a hosted MCP connector for Hermes or another MCP client.
- Outbound send fails with `MessageRejectedError` / 403 / `Recipient(s) blocked … bounced` (auto send-block suppression).
- User asks why AgentMail bounced, how to unblock a recipient, or whether a missing inbound OTP is the same bounce issue.
- User asks to **send email** to a customer, supplier, or team member.

## Outbound email (Feina — mandatory)

1. **Draft in Telegram first:** show **To/Cc/Bcc**, **subject**, and full **body**.
2. Wait for an **explicit yes** from the client before calling `send_message` or Composio Gmail send tools.
3. Use `${AGENTMAIL_INBOX}` as the default from-address unless the client specifies another connected inbox.
4. Do **not** auto-CC Feina staff or third parties unless the client included them in the approved draft.
5. For inbox triage: check Composio Gmail (if connected) and `${AGENTMAIL_INBOX}`; summarize drafts; never send without approval.

## Prerequisites

- Direct AgentMail path:
  - AgentMail account/API key from `https://console.agentmail.to`, or use first-time agent signup.
  - Environment variable: `AGENTMAIL_API_KEY=am_...`.
  - Optional CLI install: `npm install -g agentmail-cli`.
- AgentMail hosted MCP path:
  - MCP URL: `https://mcp.agentmail.to/mcp`.
  - OAuth-capable clients can authenticate via AgentMail Console.
  - API-key clients can pass the key as `?apiKey=YOUR_API_KEY` or `x-api-key` header.
- Composio path:
  - Composio CLI installed and authenticated: `curl -fsSL https://composio.dev/install | bash`, then `composio login`.
  - Environment variable for SDK work: `COMPOSIO_API_KEY=...`.
  - Use a stable Composio `user_id`; avoid `default` in production.
  - Composio's AgentMail toolkit slug is `agent_mail`; its auth type is API key.
  - Known Composio AgentMail tools: `AGENT_MAIL_CREATE_INBOX`, `AGENT_MAIL_GET_MESSAGE`, `AGENT_MAIL_LIST_INBOXES`, `AGENT_MAIL_LIST_MESSAGES`, `AGENT_MAIL_SEND_EMAIL`.

## How to Run

Use the `terminal` tool for all shell commands. Use `search_files` or `read_file` to inspect local `.env` files before changing configuration, and use `patch` or `write_file` rather than shell redirection when editing files. For Hermes MCP setup, first run `hermes mcp add --help` through `terminal` and then add the AgentMail server with a URL/auth form supported by the current Hermes build.

## Quick Reference

| Surface | Command / endpoint |
|---|---|
| Agent signup | `agentmail agent sign-up --human-email you@example.com --username my-agent` |
| Signup API | `POST https://api.agentmail.to/agent/sign-up` |
| Verify OTP | `agentmail agent verify --otp-code 123456` |
| Verify API | `POST https://api.agentmail.to/agent/verify` |
| API key env | `export AGENTMAIL_API_KEY=am_...` |
| Create inbox | `agentmail inboxes create` |
| List inboxes | `agentmail inboxes list` |
| Send email | `agentmail inboxes:messages send --inbox-id inb_xxx --to user@example.com --subject "Hello" --text "Hi there"` |
| Reply | `agentmail inboxes:messages reply --inbox-id <inbox_id> --message-id <message_id> --text "..."` |
| List threads | `agentmail inboxes:threads list --inbox-id inb_xxx` |
| Webhook | `agentmail webhooks create --event-type message.received --url https://example.com/webhook` |
| AgentMail MCP | `https://mcp.agentmail.to/mcp` |
| Send block GET | `GET /v0/lists/send/block/{email}` |
| Send block DELETE | `DELETE /v0/lists/send/block/{email}` |
| Composio install | `curl -fsSL https://composio.dev/install | bash` |
| Composio login | `composio login` |
| Composio search | `composio search "agentmail email inbox"` |
| Composio link | `composio link <toolkit>` |
| Composio schema | `composio execute <TOOL_SLUG> --get-schema` |

## Procedure

1. **Determine the requested access path.**
   - If the user wants fastest setup, use direct AgentMail CLI/API.
   - If they specifically want MCP, use AgentMail hosted MCP.
   - If they say “via Composio too,” verify Composio has a relevant toolkit/tool first; do not invent tool slugs.

2. **Check local prerequisites.** Invoke through `terminal`:
   ```bash
   command -v node || true
   command -v npm || true
   command -v agentmail || true
   command -v composio || true
   printenv AGENTMAIL_API_KEY >/dev/null && echo AGENTMAIL_API_KEY=set || echo AGENTMAIL_API_KEY=missing
   printenv COMPOSIO_API_KEY >/dev/null && echo COMPOSIO_API_KEY=set || echo COMPOSIO_API_KEY=missing
   ```
   Completion criterion: you know which CLIs and keys are present without printing secret values.

3. **Install the direct AgentMail CLI when needed.** Invoke through `terminal`:
   ```bash
   npm install -g agentmail-cli
   agentmail --version
   ```
   Completion criterion: `agentmail --version` exits successfully.

4. **Obtain AgentMail credentials.**
   - Existing user path: get an API key from `https://console.agentmail.to` and store it as `AGENTMAIL_API_KEY`.
   - First-time agent path, if the user provides the human email:
     ```bash
     agentmail agent sign-up \
       --human-email you@example.com \
       --username my-agent
     ```
     Then set `AGENTMAIL_API_KEY` from the response and verify the OTP:
     ```bash
     agentmail agent verify --otp-code 123456
     ```
   Completion criterion: API key is available and verified if using first-time agent signup.

5. **Smoke-test direct AgentMail.** Invoke through `terminal`:
   ```bash
   agentmail inboxes list --format json
   agentmail inboxes create --display-name "Hermes AgentMail Smoke Test" --format json
   ```
   Completion criterion: list succeeds and create returns an inbox identifier or email address.

6. **Send only after explicit client approval** (see Outbound email above). Prefer both `text` and `html`. MCP example shape:

   ```json
   {
     "inboxId": "${AGENTMAIL_INBOX}",
     "to": ["recipient@example.com"],
     "subject": "...",
     "text": "...",
     "html": "..."
   }
   ```

   Completion criterion: send returns `messageId`/`threadId` and matches the approved draft.

7. **Add AgentMail hosted MCP when the user wants MCP access.** First inspect the active Hermes syntax:
   ```bash
   hermes mcp add --help
   ```
   Then add the hosted server using the current Hermes-supported URL flow. AgentMail’s hosted MCP server is:
   ```text
   https://mcp.agentmail.to/mcp
   ```
   If the MCP client cannot do OAuth, AgentMail supports API key auth via:
   ```text
   https://mcp.agentmail.to/mcp?apiKey=YOUR_API_KEY
   x-api-key: YOUR_API_KEY
   ```
   Completion criterion: `hermes mcp test agentmail` or the equivalent current Hermes MCP test command succeeds.

8. **Verify Composio AgentMail access.** Install/login if needed, then invoke through `terminal`:
   ```bash
   curl -fsSL https://composio.dev/install | bash
   composio login
   composio whoami
   composio search "agentmail email inbox"
   ```
   Expected toolkit slug from Composio's public toolkit page: `agent_mail`. Expected tools: `AGENT_MAIL_CREATE_INBOX`, `AGENT_MAIL_GET_MESSAGE`, `AGENT_MAIL_LIST_INBOXES`, `AGENT_MAIL_LIST_MESSAGES`, `AGENT_MAIL_SEND_EMAIL`. Completion criterion: Composio login succeeds and search or schemas confirm the `agent_mail` toolkit/tools for the active account.

9. **Connect and execute through Composio only after discovering exact names.** Use the exact toolkit and tool slug returned by `composio search`:
   ```bash
   composio link <toolkit>
   composio execute <TOOL_SLUG> --get-schema
   composio execute <TOOL_SLUG> -d '{ /* schema-valid input */ }'
   ```
   Completion criterion: schema retrieval succeeds and a low-risk read/list tool executes successfully.

10. **For Composio SDK/MCP projects, use current v3 session patterns.** Do not use old `ComposioToolSet` or app/action terminology. Python native-tools pattern:
    ```python
    from composio import Composio

    composio = Composio()
    session = composio.create(user_id="user_123")
    tools = session.tools()
    ```
    MCP pattern:
    ```python
    from composio import Composio

    composio = Composio()
    session = composio.create(user_id="user_123", mcp=True)

    mcp_url = session.mcp.url
    mcp_headers = session.mcp.headers
    ```
    Completion criterion: the project stores the Composio session ID for reuse or can recreate a scoped session intentionally.

## Outbound bounce suppression (send block)

When MCP `send_message` or `POST .../messages/send` returns:

```text
MessageRejectedError 403
Recipient(s) blocked: user@domain.com (bounced)
```

AgentMail is **refusing the send before mail leaves**. A previous delivery attempt bounced/rejected/complained, and AgentMail auto-added an **org-level send block**. Known-good customer addresses can still sit here after a one-off historical bounce.

### Diagnose and fix

```bash
# Never print AGENTMAIL_API_KEY
curl -sS -H "Authorization: Bearer $AGENTMAIL_API_KEY" \
  "https://api.agentmail.to/v0/lists/send/block/user@domain.com"
# 200 + reason "bounced" or "Unsubscribed via List-Unsubscribe" → suppressed; 404 → not blocked
# If JSON has read_only:true, DELETE returns 409 — do not loop; fall back to the client Gmail Composio
# 413 on send: compress attachments to email JPEG or Drive-link large packs

# Only if address is known-good AND not read_only:
curl -sS -X DELETE -H "Authorization: Bearer $AGENTMAIL_API_KEY" \
  "https://api.agentmail.to/v0/lists/send/block/user@domain.com"
# expect 204; re-GET → 404; then resend (text + html)
```

Also: `GET /v0/lists/send/block` (paginated), `GET /v0/lists/receive/block`, `GET /v0/metrics` (`message.bounced` / `rejected` / `complained`).

### Outbound vs inbound (do not conflate)

| Pattern | Direction | Where to look |
|---|---|---|
| 403 `blocked … bounced` on **send** | Outbound | `send/block` auto-suppression |
| Third-party OTP never appears | Inbound | Inbox list + `receive/block` (often empty) — product/gate, not send-block |
| Other mail from same vendor **does** land | Inbound OK | Missing type is product-side |

Fallback: operator Gmail (Composio) if AgentMail still blocked or policy forbids unblocking.

Full cheatsheet: `references/bounce-suppression-send-block.md`.

## Pitfalls

- Do not assume a Composio AgentMail toolkit exists in the user’s account. Run `composio search "agentmail email inbox"` and use only returned toolkits/tool slugs.
- Do not print API keys. Check secret presence with `printenv NAME >/dev/null` style commands.
- The AgentMail agent signup flow is for first-time users; human email addresses already signed up with AgentMail will not work there.
- The AgentMail signup endpoint is idempotent; calling it again with the same email rotates the API key and resends the OTP if expired.
- For AgentMail MCP, OAuth and API-key auth are different paths. Use OAuth for clients that support it; use `?apiKey=` or `x-api-key` for clients that do not.
- AgentMail send/reply has a recipient limit of 50 total across `to`, `cc`, and `bcc`.
- For outbound email, provide both `text` and `html` when possible; AgentMail docs call this a deliverability best practice.
- In Composio v3, use `composio.create(user_id)` and `session.tools()` or `session.mcp.url`; do not use old “entity ID,” “actions,” “apps,” or `ComposioToolSet` patterns.
- **403 blocked/bounced is not “mailbox invalid.”** Inspect `send/block` first; often a one-line DELETE, not a domain investigation.
- **Do not treat missing inbound fund/OTP mail as send-block.** If other vendor messages land, it is a product/gate issue.
- **Send block is org-wide** across all inboxes until the entry is removed.
- Do not mass-delete the entire send/block list; clear known-good addresses only.
- Feina policy: read/search/list + drafts OK; show the full draft in Telegram and send only after explicit client approval (`SOUL.md`).
- Ground drip voice from **prior messages on that inbox** (`AGENT_MAIL_LIST_MESSAGES` / `GET_MESSAGE`) before writing new subjects.
- Check custom-domain DNS status on the customer inbox before volume; PENDING domains degrade deliverability.

## Verification

A setup is verified when this `terminal` check succeeds without exposing secrets:

```bash
agentmail inboxes list --format json >/tmp/agentmail-inboxes.json && \
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('/tmp/agentmail-inboxes.json')
print('agentmail_direct_ok=', p.exists() and p.stat().st_size > 0)
PY
```

For Composio, additionally verify:

```bash
composio whoami && composio search "agentmail email inbox"
```

If the Composio search does not return AgentMail-specific tools, report direct AgentMail as working and Composio AgentMail access as unverified/unavailable in the current Composio surface.

Bounce fix is verified when: `GET send/block/{email}` is 404 after DELETE, and a subsequent send returns a real `messageId`/`threadId`.

Outbound policy is verified when every real send matches a draft the client explicitly approved in chat.

## References

- `references/inbound-otp-vs-send-block.md` — do not conflate inbound OTP miss with send-block

