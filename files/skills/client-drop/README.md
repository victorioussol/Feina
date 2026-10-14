# Client industry skills (drop-in)

Feina does **not** bake industry packs (gym KPI, reconciliation, etc.) into the base image.

After bootstrap, copy skill folders here on the client computer:

`/root/.hermes/skills/client-drop/<pack-name>/`

Each pack should be a normal Hermes skill tree (`SKILL.md` + references). Restart the gateway after adding files:

```bash
supervisorctl restart hermes-gateway
```

Feina ops can tar/copy packs over the Orgo bash API during launch.
