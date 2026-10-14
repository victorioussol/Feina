---
name: secret-manager-setup
description: "Set up 1Password service-account flows and op:// secret references for Feina client agents; Composio-vs-Hermes boundary; OpenAI Codex OAuth on headless VMs."
version: 1.4.1
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [secrets, 1password, bitwarden, op-cli, hermes, setup]
---

# Secret Manager Setup

Use this skill when configuring an agent or Hermes installation to load API keys and tokens from an external secret manager instead of storing raw secrets directly in `.env` files. It is especially relevant for headless Linux VMs, Orgo computers, gateway agents, cron jobs, and long-running Hermes profiles.

Authoritative product docs still win over this skill. For Hermes-specific commands, verify against `hermes secrets --help` and the official Hermes secrets docs when available.

## Core workflow

1. Identify the secret manager and runtime shape.
   - Headless server or Orgo VM: prefer a service-account token or machine credential.
   - Personal laptop with GUI unlock: interactive desktop-app integration may be acceptable.
   - Long-running Hermes gateway or cron: avoid short-lived interactive sessions unless only testing.

2. Install and verify the vendor CLI.
   - 1Password CLI command: `op`.
   - Check: `command -v op && op --version`.

3. Enable the Hermes secret source.
   - Inspect support: `hermes secrets --help`.
   - 1Password help: `hermes secrets 1password --help`.
   - Setup: `hermes secrets 1password setup --binary-path "$(command -v op)"`.

4. Authenticate the CLI in a way appropriate to the runtime.
   - Recommended for headless Hermes: `OP_SERVICE_ACCOUNT_TOKEN`.
   - Less durable: `op signin` interactive session, which can expire.

5. Map Hermes env vars to secret references.
   - 1Password reference shape: `op://Vault Name/Item Name/Field Name`.
   - Example: `hermes secrets 1password set OPENROUTER_API_KEY 'op://Automation/Hermes Agent/OPENROUTER_API_KEY'`.

6. **Validate before trusting a new field.**
   - Field exists ≠ correct secret. Users often paste the wrong value (UUID, other product key).
   - `op read` the reference; print only metadata (length, prefix class), never the secret.
   - Call the vendor auth API (e.g. GitHub `GET /user`) and require HTTP 200.
   - **Only then** run `hermes secrets 1password set` + sync.

7. Verify resolution before removing local secrets.
   - Dry run: `hermes secrets 1password sync`.
   - Apply/export if needed by current shell: `hermes secrets 1password sync --apply`.
   - Status: `hermes secrets 1password status`.
   - Vendor-level test: `op read 'op://Vault/Item/Field'` (do not echo the value into chat).

8. Only after successful resolution, consider cleaning raw duplicated secrets from `.env`.
   - Keep non-secret config values in `.env`.
   - Do not delete raw secrets until the agent can restart and resolve references successfully.

## 1Password on headless VMs

For a long-running agent VM, ask for or create a 1Password service account with read access to the vault/items containing the agent secrets. The user usually needs to provide the service account token, commonly resembling `ops_...`, and the vault/item/field names or exact `op://...` references.

If the user wants the agent to create the 1Password item from an existing `.env`, the service account needs `read_items,write_items` on a non-personal vault. 1Password service accounts cannot access Personal/Private vaults, so ask the user to create or name a shared/custom vault such as `Feina - <Client>` or `Agent Secrets`.

Manual account login is possible but inferior for a server because `op signin` sessions are short-lived. Use it for temporary testing only unless the user explicitly wants that trade-off.

When a service-account token is pasted into chat or logs, finish the setup, verify it, then recommend rotating that token and replacing `OP_SERVICE_ACCOUNT_TOKEN`. The token is the bootstrap secret and must remain protected even after other API keys move into 1Password.

## Pitfalls

- Do not confuse the 1Password SSH agent with 1Password secret resolution. A config like `IdentityAgent "~/Library/Group Containers/.../agent.sock"` is for SSH private keys on the user's local Mac, not for resolving API keys on a Linux VM.
- Do not claim setup is complete just because the integration is enabled. Complete setup requires an authenticated CLI plus at least one mapped reference and a successful sync/read test.
- Missing `op` is a setup state, not a durable tool limitation. Install the CLI, then retry.
- Service-account permissions matter. A token may authenticate but still fail to read a vault/item/field if the account lacks access.
- Do not pass migrated secret values as `op item create` assignment arguments. Assignment arguments can be visible in process listings or shell history. Use a JSON template through stdin for secret-valued fields.
- Do not remove raw `.env` secrets immediately after a successful Hermes sync if external scripts or services source `.env` directly. First verify those services either run under Hermes secret resolution or can read the replacement source.
- If a user pasted a service-account token into a chat transcript, treat setup as provisional. After verification, recommend token rotation and replace only `OP_SERVICE_ACCOUNT_TOKEN` with the new token.
- **Never dump full `op item get --format=json` into the transcript** when the item holds multiple API keys; use single-field `op read` and print metadata only.
- **Do not map a secret that fails its vendor auth test** (e.g. GitHub 401 with a UUID-shaped "PAT").
- Discovery endpoints are not always authentication checks. Vercel AI Gateway `GET /v1/models` may return HTTP 200 with an invalid credential; require a minimal authenticated `POST /v1/chat/completions` before trusting the key.
- Vercel AI Gateway keys are one-time `vck_…` secrets. A 36-character UUID is the key ID, not the bearer token (`apiKeyString`); create a new key because the plaintext cannot be retrieved later.
- Replacing a 1Password field does not refresh secrets already injected into a running Hermes process. Clear `~/.hermes/cache/op_cache.json`, then fully quit and restart the CLI or restart the gateway. `/reload` only rereads `.env`; it does not rerun external secret sources such as 1Password.
- **Query-string MCP credentials can leak in CLI diagnostics.** A config such as `url: https://example/mcp?key=${API_KEY}` safely keeps the raw key out of `config.yaml`, but `hermes mcp test <name>` currently prints the fully resolved URL. Do not run that command in shared logs/transcripts for query-key MCPs. Prefer a minimal vendor/MCP initialize probe whose output reports only HTTP status and protocol markers, or use header auth when the vendor supports it. If a resolved URL is printed into a transcript, treat the key as exposed and recommend rotation.
- GitHub PATs: expect `ghp_…` or `github_pat_…`. Len-36 UUID values are wrong even if the field is named `GITHUB_PAT` (common paste = Latitude-style UUID).
- Map **both** `GITHUB_TOKEN` and `GH_TOKEN` to the same PAT field so curl, git `x-access-token`, and future `gh` all resolve.
- After GitHub mapping: Composio `github` toolkit is fine for lightweight API recon; use the PAT for private shallow clones when reading source trees.
- Bundled `github-auth` / `github-repo-management` may be unpatchable in curator mode; keep durable GitHub+1Password procedure **here** and in `vault-managed-customer-agents/references/product-code-repo-recon.md` + `github-collaborator-invites.md` (username API accept vs email Gmail invites).
- Collaborator invites sent to an **email** may not appear on `GET /user/repository_invitations` for the PAT login — check Gmail before telling the user to re-invite.

## Feina Basic field catalog (Hermes Agent Secrets)

Canonical item: `op://Feina/Hermes Agent Secrets/<FIELD>` (per-client vault name may be `Feina - <Client>` — update references accordingly).

| Env var | 1P field | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | same | `sk-or-…`; Basic billing with hard cap |
| `TELEGRAM_BOT_TOKEN` | same | From QR pairing or BotFather |
| `AGENTMAIL_API_KEY` | same | Agent inbox |
| `AGENTMAIL_INBOX` | same | `…@agentmail.to` |
| `COMPOSIO_CONSUMER_KEY` | same | `ck_…` per client |
| `LATITUDE_API_KEY` | same | Optional until Feina enables tracing |
| `LATITUDE_PROJECT` | same | e.g. `feina-vince` |

**Never map on client computers:** Orgo fleet-control API keys or any other client's secrets.

## Composio vs Hermes secrets

Composio connections do not export raw credentials for Hermes `secrets.onepassword` maps, `.env`, or `auth.json`. Treat Composio as a parallel tool proxy.

## OpenAI Codex OAuth (Feina client ChatGPT accounts)

Use `feina-onboard model-codex` or `hermes auth add openai-codex` on the client VM. Store subscription credentials in `auth.json`, not 1Password, unless Feina policy changes.

## Useful references

- `references/onepassword-hermes.md` — command sequence and safe reads
- `references/composio-vs-hermes-auth.md` — Composio does not export Hermes credentials
- `references/openai-codex-oauth-fleet-audit.md` — OAuth usage audit patterns
