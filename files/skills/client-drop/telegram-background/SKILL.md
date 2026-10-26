---
name: telegram-background
description: Acknowledge long Telegram requests immediately, run one background job per chat, and share the AFSA lock with the 04:00 cron.
version: 1.1.0
metadata:
  hermes:
    tags: [Telegram, Delegation, AFSA]
---

# Instant reply

Off until `/root/.hermes/feina-client/enabled/telegram-background` exists. The always-on instructions live in `SOUL.md` under "Long Telegram work" because a skill the model forgets to load does not help a 40-minute turn.

On Hermes v0.21.7, in a gateway chat, `delegate_task` returns a handle and the result comes back as a later message. Cron jobs and one-shot CLI sessions do not do that: they wait. So the 04:00 AFSA job is a no-agent script, not a delegated model turn.

`background=true` on `delegate_task` is ignored on v0.21.7. Do not pass it.

Subagents cannot send Telegram and cannot create cron jobs. The parent sends the acknowledgement and the final result through `feina_telegram_turn.py`, which uses the bot token already on the machine. If that send fails, the script prints the sentence so you can say it yourself.

One active long job per chat. A second request is told, in the client's language, that it is queued. The queue is one deep step at a time: when `finish` prints `queued_next`, delegate that label and end the turn.

Anything that touches Membr or the workbook runs under `feina_with_lock.py`. Exit 75 means the night job holds the lock.

## What v0.21.7 does not do

The gateway can still start two inbound turns before either of them reaches the lock. The lock stops the Membr work from overlapping; it cannot stop Hermes from accepting the second message. A hard single-flight queue inside the gateway is not part of this version. v0.22 adds a stuck-turn watchdog and loop guardrails, which are extra safety, not a requirement for this script.
