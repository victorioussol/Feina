# Telegram long work

This file is installed into the gateway working directory only when the telegram-background part is enabled. Hermes v0.21.7 loads `AGENTS.md` from the process working directory (often `/root`), not from `HERMES_HOME`.

Follow the "Long Telegram work" section of `SOUL.md`. The enable flag is `/root/.hermes/feina-client/enabled/telegram-background`.
