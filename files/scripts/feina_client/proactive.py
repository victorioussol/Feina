"""Quiet, capped proactive messages. Nothing here sends mail or member texts.

External messages are drafts. The script prints a Telegram note or prints
nothing. Quiet hours, the daily cap, and the ignore pause are pure functions
so they can be tested without a clock daemon.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .runtime import MADRID, madrid_now

QUIET_START = 22 * 60
QUIET_END = 8 * 60
DAILY_CAP = 2
IGNORE_LIMIT = 3

TEXTS = {
    "fr": {
        "ack": "Je m'en occupe. Je vous écris dès que c'est prêt.",
        "queued": "Je termine encore une tâche. Celle-ci est en file d'attente.",
        "nightly_busy": "Le traitement de la nuit est en cours. Votre demande est en file d'attente.",
        "daily_clean": "✅ AFSA Ingresos est prêt pour le {date}. Aucun écart.",
        "daily_bad": "✅ AFSA Ingresos est prêt pour le {date}. {n} écart(s) à vérifier :\n{lines}\nDites-moi si vous voulez le détail.",
        "monday_empty": "",
        "monday": "Lundi — ce qui a bougé :\n{lines}",
        "debits_none": "",
        "debits": "Prélèvements refusés : {n}.\n{lines}\nBrouillons ci-dessous. Rien n'est envoyé sans votre oui.\n{drafts}",
        "draft": "Brouillon pour {ref} ({amount} €) : bonjour, le prélèvement du {date} n'est pas passé. Pouvez-vous vérifier votre moyen de paiement ?",
        "tax": "Rappel AEAT : {label} le {date} ({phase}). Je peux préparer le brouillon pour votre gestor si vous le voulez.",
        "month": "Fin de mois. Brouillon pour le gestor, pas envoyé.\nÀ : {to}\nObjet : {subject}\n{body}\nRépondez oui pour l'envoyer.",
        "remind": "Rappel : {text}",
        "pause": "Vous n'avez pas répondu à trois messages « {kind} ». Je les mets en pause. Répondez « reprendre » pour les garder.",
        "phase_first": "dans 10 jours",
        "phase_followup": "c'est aujourd'hui",
    },
    "es": {
        "ack": "Me pongo con ello. Le escribo en cuanto esté listo.",
        "queued": "Sigo con otra tarea. La suya queda en cola.",
        "nightly_busy": "El cierre de la noche está en curso. Su petición queda en cola.",
        "daily_clean": "✅ AFSA Ingresos está listo para el {date}. Ningún descuadre.",
        "daily_bad": "✅ AFSA Ingresos está listo para el {date}. {n} descuadre(s):\n{lines}\nDígame si quiere el detalle.",
        "monday": "Lunes — solo lo que se ha movido:\n{lines}",
        "debits": "Adeudos devueltos: {n}.\n{lines}\nBorradores debajo. No se envía nada sin su sí.\n{drafts}",
        "draft": "Borrador para {ref} ({amount} €): hola, el adeudo del {date} no se ha cobrado. ¿Puede revisar el método de pago?",
        "tax": "Aviso AEAT: {label} el {date} ({phase}). Puedo preparar el borrador para su gestor si quiere.",
        "month": "Cierre de mes. Borrador para el gestor, no enviado.\nPara: {to}\nAsunto: {subject}\n{body}\nResponda sí para enviarlo.",
        "remind": "Recordatorio: {text}",
        "pause": "No ha respondido a tres mensajes « {kind} ». Los pauso. Responda « reanudar » para seguir.",
        "phase_first": "dentro de 10 días",
        "phase_followup": "es hoy",
    },
    "en": {
        "ack": "On it. I'll message you when it's done.",
        "queued": "I'm still on another task. This one is queued.",
        "nightly_busy": "The night job is still running. Your request is queued.",
        "daily_clean": "✅ AFSA Ingresos is ready for {date}. No mismatches.",
        "daily_bad": "✅ AFSA Ingresos is ready for {date}. {n} mismatch(es):\n{lines}\nTell me if you want the detail.",
        "monday": "Monday — only what moved:\n{lines}",
        "debits": "Failed direct debits: {n}.\n{lines}\nDrafts below. Nothing is sent without your yes.\n{drafts}",
        "draft": "Draft for {ref} ({amount}): hello, the {date} collection did not go through. Could you check the payment method?",
        "tax": "AEAT reminder: {label} on {date} ({phase}). I can draft the note for your accountant if you want.",
        "month": "Month end. Draft for the accountant, not sent.\nTo: {to}\nSubject: {subject}\n{body}\nReply yes to send it.",
        "remind": "Reminder: {text}",
        "pause": "You ignored three « {kind} » messages. I've paused them. Reply « resume » to keep them.",
        "phase_first": "in 10 days",
        "phase_followup": "it is today",
    },
}


def text(lang: str, key: str, **kwargs) -> str:
    table = TEXTS.get(lang) or TEXTS["es"]
    template = table.get(key) or TEXTS["es"].get(key) or ""
    return template.format(**kwargs)


def in_quiet_hours(now: datetime) -> bool:
    now = madrid_now(now)
    minutes = now.hour * 60 + now.minute
    return minutes >= QUIET_START or minutes < QUIET_END


def in_send_window(now: datetime, hour: int, tolerance_minutes: int = 20) -> bool:
    now = madrid_now(now)
    target = hour * 60
    minutes = now.hour * 60 + now.minute
    return abs(minutes - target) <= tolerance_minutes


def _kind_state(state: dict, kind: str) -> dict:
    kinds = state.setdefault("kinds", {})
    return kinds.setdefault(
        kind,
        {"ignores": 0, "awaiting": False, "paused": False, "pause_asked": False},
    )


def sends_today(state: dict, day: str) -> int:
    return sum(1 for row in state.get("sends") or [] if row.get("day") == day and row.get("counts", True))


def gate(
    state: dict,
    kind: str,
    *,
    has_content: bool,
    now: datetime,
    counts: bool = True,
    ignore_quiet: bool = False,
) -> str:
    """Return send, silent, quiet, rate_limit, or pause."""
    now = madrid_now(now)
    st = _kind_state(state, kind)
    if st.get("paused"):
        if not st.get("pause_asked"):
            st["pause_asked"] = True
            return "pause"
        return "silent"
    if not has_content:
        return "silent"
    if in_quiet_hours(now) and not ignore_quiet:
        return "quiet"
    if counts and sends_today(state, now.date().isoformat()) >= DAILY_CAP:
        return "rate_limit"
    if st.get("awaiting"):
        st["ignores"] = int(st.get("ignores") or 0) + 1
        st["awaiting"] = False
    if int(st.get("ignores") or 0) >= IGNORE_LIMIT:
        st["paused"] = True
        st["pause_asked"] = True
        return "pause"
    return "send"


def mark_sent(state: dict, kind: str, now: datetime, *, counts: bool = True) -> None:
    now = madrid_now(now)
    st = _kind_state(state, kind)
    st["awaiting"] = True
    state.setdefault("sends", []).append(
        {"kind": kind, "day": now.date().isoformat(), "at": now.isoformat(), "counts": counts}
    )


def mark_inbound(state: dict) -> None:
    for st in (state.get("kinds") or {}).values():
        if st.get("awaiting"):
            st["awaiting"] = False
            st["ignores"] = 0


def unpause(state: dict, kind: str) -> None:
    st = _kind_state(state, kind)
    st["paused"] = False
    st["pause_asked"] = False
    st["ignores"] = 0
    st["awaiting"] = False


def first_working_day(year: int, month: int) -> date:
    cursor = date(year, month, 1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor


def tax_deadlines(year: int) -> list[dict]:
    items = []
    for month in (1, 4, 7, 10):
        items.append(
            {
                "date": date(year, month, 20),
                "kind": "quarterly",
                "label": "AEAT modelo 303 / 111 / 115",
            }
        )
    items.append(
        {
            "date": date(year, 1, 30),
            "kind": "annual",
            "label": "AEAT declaracion anual",
        }
    )
    return items


def due_tax_notices(today: date, state: dict) -> list[dict]:
    notices = []
    tax_state = state.setdefault("tax", {})
    years = {today.year, today.year + 1}
    for year in sorted(years):
        for item in tax_deadlines(year):
            delta = (item["date"] - today).days
            key = item["date"].isoformat()
            sent = tax_state.setdefault(key, {})
            if delta == 10 and not sent.get("first"):
                notices.append({**item, "phase": "first", "key": key})
            elif delta == 0 and sent.get("first") and not sent.get("followup") and not sent.get("replied"):
                notices.append({**item, "phase": "followup", "key": key})
    return notices


def mark_tax_sent(state: dict, key: str, phase: str) -> None:
    sent = state.setdefault("tax", {}).setdefault(key, {})
    if phase == "first":
        sent["first"] = True
    elif phase == "followup":
        sent["followup"] = True


def add_reminder(state: dict, when: datetime, text_body: str, *, allow_quiet: bool = False) -> dict:
    when = madrid_now(when)
    item = {
        "id": f"{when.strftime('%Y%m%dT%H%M%S')}-{len(state.get('reminders') or [])}",
        "when": when.isoformat(),
        "text": text_body.strip(),
        "sent": False,
        "allow_quiet": allow_quiet,
        "requested": True,
    }
    state.setdefault("reminders", []).append(item)
    return item


def due_reminders(state: dict, now: datetime) -> list[dict]:
    now = madrid_now(now)
    ready = []
    for item in state.get("reminders") or []:
        if item.get("sent"):
            continue
        when = datetime.fromisoformat(item["when"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=MADRID)
        if when > now:
            continue
        if in_quiet_hours(now) and not item.get("allow_quiet"):
            continue
        ready.append(item)
    return ready


def notable_changes(current: dict, previous: dict, *, minimum: float = 1, percent: float = 10) -> list[str]:
    """Return labels that moved. Empty means the Monday note stays silent."""
    lines = []
    keys = sorted(set(current) | set(previous))
    for key in keys:
        if key.startswith("_"):
            continue
        try:
            now_v = float(current.get(key) or 0)
            then_v = float(previous.get(key) or 0)
        except (TypeError, ValueError):
            continue
        diff = abs(now_v - then_v)
        base = abs(then_v) if then_v else 0
        moved = diff >= minimum and (base == 0 or (diff / base) * 100 >= percent)
        if moved:
            lines.append(f"{key}: {then_v:g} → {now_v:g}")
    return lines


def compose_daily(lang: str, night: dict | None, *, when_clean: bool) -> str | None:
    if not night or not night.get("confirmed_write"):
        return None
    mismatches = list(night.get("mismatches") or [])
    when = night.get("business_date") or ""
    if not mismatches:
        if not when_clean:
            return None
        return text(lang, "daily_clean", date=when)
    lines = "\n".join(f"- {row.get('kind')} {row.get('ref')} {row.get('amount')}" for row in mismatches)
    return text(lang, "daily_bad", date=when, n=len(mismatches), lines=lines)


def compose_monday(lang: str, changes: list[str], debits: list[dict], business_date: str) -> str | None:
    parts = []
    if changes:
        parts.append(text(lang, "monday", lines="\n".join(f"- {line}" for line in changes)))
    if debits:
        lines = "\n".join(f"- {row.get('ref')} {row.get('amount')}" for row in debits)
        drafts = "\n".join(
            text(
                lang,
                "draft",
                ref=row.get("member_ref") or row.get("ref") or "—",
                amount=row.get("amount") or "",
                date=business_date,
            )
            for row in debits
        )
        parts.append(text(lang, "debits", n=len(debits), lines=lines, drafts=drafts))
    if not parts:
        return None
    return "\n\n".join(parts)


def compose_tax(lang: str, notices: list[dict]) -> str | None:
    if not notices:
        return None
    rows = []
    for notice in notices:
        phase = text(lang, "phase_first" if notice["phase"] == "first" else "phase_followup")
        rows.append(
            text(
                lang,
                "tax",
                label=notice["label"],
                date=notice["date"].isoformat(),
                phase=phase,
            )
        )
    return "\n".join(rows)


def compose_month(lang: str, today: date, *, to: str, subject: str, body: str) -> str | None:
    if today != first_working_day(today.year, today.month):
        return None
    return text(lang, "month", to=to, subject=subject, body=body)


def external_send_allowed() -> bool:
    """Member-facing and accountant-facing sends stay drafts."""
    return False


def morning_bundle(
    state: dict,
    *,
    lang: str,
    now: datetime,
    enabled: dict,
    night: dict | None,
    changes: list[str] | None = None,
    debits: list[dict] | None = None,
    gestor_to: str = "",
    gestor_subject: str = "",
    gestor_body: str = "",
    when_clean: bool = True,
) -> str | None:
    """One 09:00 pass. Each behaviour is skipped unless its flag is on."""
    now = madrid_now(now)
    parts: list[str] = []
    if enabled.get("tax"):
        notices = due_tax_notices(now.date(), state)
        body = compose_tax(lang, notices)
        msg = take_message(state, "tax", body, now, lang)
        if msg and body and msg != text(lang, "pause", kind="tax"):
            for notice in notices:
                mark_tax_sent(state, notice["key"], notice["phase"])
        if msg:
            parts.append(msg)
    if enabled.get("daily"):
        msg = take_message(
            state,
            "daily",
            compose_daily(lang, night, when_clean=when_clean),
            now,
            lang,
        )
        if msg:
            parts.append(msg)
    if enabled.get("monday") and now.weekday() == 0:
        msg = take_message(
            state,
            "monday",
            compose_monday(lang, changes or [], debits or [], (night or {}).get("business_date") or now.date().isoformat()),
            now,
            lang,
        )
        if msg:
            parts.append(msg)
    if enabled.get("month_end"):
        msg = take_message(
            state,
            "month_end",
            compose_month(lang, now.date(), to=gestor_to, subject=gestor_subject, body=gestor_body),
            now,
            lang,
        )
        if msg:
            parts.append(msg)
    if not parts:
        return None
    return "\n\n".join(parts)


def reminder_lines(state: dict, *, lang: str, now: datetime) -> str | None:
    due = due_reminders(state, now)
    if not due:
        return None
    sent_any = False
    lines = []
    for item in due:
        msg = take_message(
            state,
            "reminder",
            text(lang, "remind", text=item["text"]),
            now,
            lang,
            counts=False,
            ignore_quiet=bool(item.get("allow_quiet")),
        )
        if not msg:
            continue
        item["sent"] = True
        lines.append(msg)
        sent_any = True
    if not sent_any:
        return None
    return "\n".join(lines)


def take_message(
    state: dict,
    kind: str,
    body: str | None,
    now: datetime,
    lang: str,
    *,
    counts: bool = True,
    ignore_quiet: bool = False,
) -> str | None:
    decision = gate(
        state,
        kind,
        has_content=bool(body),
        now=now,
        counts=counts,
        ignore_quiet=ignore_quiet,
    )
    if decision == "pause":
        mark_sent(state, kind, now, counts=True)
        return text(lang, "pause", kind=kind)
    if decision != "send" or not body:
        return None
    mark_sent(state, kind, now, counts=counts)
    return body
