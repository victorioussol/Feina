# Example Orgo ops session (Feina operators)

Session notes pattern for configuring Orgo from a **Feina ops machine** — not from a client agent VM.

## Target computer (example)

```text
name: example-ops-box
workspace: <feina-workspace>
computer_id: <example-computer-id>
os: linux
cpu: 8
ram_gb: 32
expected status: running
```

## CLI setup

```bash
curl -fsSL https://orgo.ai/install.sh | bash
export PATH="$HOME/.local/bin:$HOME/.orgo/node/bin:$PATH"
orgo --version
orgo computers list
```

## API key handling

- Keep `ORGO_API_KEY` on the **ops workstation** or in Feina's launch vault only.
- **Never** export `ORGO_API_KEY` into a client computer's `~/.hermes/.env` — `feina-stack` bootstrap strips it.

## Orgo MCP (ops only)

Configure stdio MCP from an ops environment when fleet control is required. Client agents must keep `orgo` MCP disabled (`feina enable orgo` is refused).

See the parent skill `orgo-cloud-computers` for REST/MCP patterns without pasting live secrets into chat.
