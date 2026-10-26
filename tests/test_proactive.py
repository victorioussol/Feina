"""Quiet hours, the daily cap, ignore-pause, and French copy."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from feina_client.proactive import (
    DAILY_CAP,
    compose_daily,
    compose_monday,
    compose_month,
    due_reminders,
    due_tax_notices,
    external_send_allowed,
    first_working_day,
    gate,
    in_quiet_hours,
    in_send_window,
    mark_sent,
    morning_bundle,
    notable_changes,
    reminder_lines,
    text,
)

MADRID = ZoneInfo("Europe/Madrid")


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=MADRID)


def test_quiet_hours_and_morning_window():
    assert in_quiet_hours(at(2026, 10, 26, 22, 0)) is True
    assert in_quiet_hours(at(2026, 10, 26, 21, 59)) is False
    assert in_quiet_hours(at(2026, 10, 26, 7, 59)) is True
    assert in_quiet_hours(at(2026, 10, 26, 8, 0)) is False
    assert in_send_window(at(2026, 10, 26, 8, 40), 9) is True
    assert in_send_window(at(2026, 10, 26, 8, 39), 9) is False
    assert in_send_window(at(2026, 10, 26, 9, 20), 9) is True
    assert in_send_window(at(2026, 10, 26, 9, 21), 9) is False


def test_rate_limit_does_not_count_as_an_ignore_and_caps_at_two():
    state = {}
    now = at(2026, 10, 26, 9, 0)
    for _ in range(DAILY_CAP):
        assert gate(state, "daily", has_content=True, now=now) == "send"
        mark_sent(state, "daily", now)
    ignores_before = state["kinds"]["daily"]["ignores"]
    assert gate(state, "tax", has_content=True, now=now) == "rate_limit"
    assert state["kinds"]["daily"]["ignores"] == ignores_before
    assert "tax" not in state["kinds"] or state["kinds"]["tax"]["ignores"] == 0


def test_three_ignored_messages_pause_the_type():
    """The daily cap is two, so the third ignore lands on a later day."""
    state = {}
    sent = 0
    decision = "send"
    days = [at(2026, 10, 26, 9, 0), at(2026, 10, 27, 9, 0), at(2026, 10, 28, 9, 0), at(2026, 10, 29, 9, 0)]
    for now in days:
        decision = gate(state, "monday", has_content=True, now=now)
        if decision == "send":
            mark_sent(state, "monday", now)
            sent += 1
    assert sent == 3
    assert decision == "pause"
    assert gate(state, "monday", has_content=True, now=days[-1]) == "silent"


def test_reminders_do_not_use_the_daily_cap_and_respect_quiet_hours():
    state = {"reminders": []}
    now = at(2026, 10, 26, 23, 0)
    from feina_client.proactive import add_reminder

    add_reminder(state, at(2026, 10, 26, 22, 30), "appeler le gestor")
    add_reminder(state, at(2026, 10, 26, 22, 40), "autre", allow_quiet=True)
    due = due_reminders(state, now)
    assert [item["text"] for item in due] == ["autre"]
    morning = at(2026, 10, 26, 9, 0)
    for _ in range(DAILY_CAP):
        assert gate(state, "daily", has_content=True, now=morning) == "send"
        mark_sent(state, "daily", morning, counts=True)
    add_reminder(state, at(2026, 10, 26, 10, 0), "appeler le gestor")
    body = reminder_lines(state, lang="fr", now=at(2026, 10, 26, 11, 0))
    assert body and "appeler le gestor" in body
    assert gate(state, "daily", has_content=True, now=at(2026, 10, 26, 11, 0)) == "rate_limit"


def test_nothing_to_say_stays_silent_and_french_copy_is_used():
    state = {}
    now = at(2026, 10, 26, 9, 0)
    assert morning_bundle(state, lang="fr", now=now, enabled={"daily": True, "monday": True}, night=None) is None
    assert state.get("sends") in (None, [])
    assert "Je m'en occupe" in text("fr", "ack")
    assert external_send_allowed() is False
    night = {
        "confirmed_write": True,
        "figures_final": True,
        "outcome": "verified_disagree",
        "business_date": "2026-10-25",
        "items": [
            {
                "receipt": "M1",
                "membr": "12.00",
                "paycomet": "10.00",
                "check": "Look up receipt M1 in Membr or Paycomet.",
            }
        ],
    }
    body = compose_daily("fr", night, when_clean=True)
    assert "écart" in body and "12.00" in body and "10.00" in body
    assert "Look up receipt M1" in body
    unverified = compose_daily(
        "fr",
        {
            "outcome": "unverified",
            "reason": "source_format_changed",
            "business_date": "2026-10-25",
            "items": [{"membr": "99.00"}],
        },
        when_clean=True,
    )
    assert "99.00" not in unverified
    assert "définitif" in unverified
    clean = compose_daily(
        "fr",
        {
            "confirmed_write": True,
            "figures_final": True,
            "outcome": "verified_match",
            "business_date": "2026-10-25",
        },
        when_clean=False,
    )
    assert clean is None


def test_monday_only_notable_changes_and_debit_drafts_need_a_yes():
    assert notable_changes({"card": 100}, {"card": 100}) == []
    assert notable_changes({"card": 111}, {"card": 100})
    assert notable_changes({"card": 105}, {"card": 100}) == []
    note = compose_monday(
        "fr",
        ["card: 100 → 111"],
        [{"ref": "H2", "amount": "25.00", "member_ref": "SOC-9"}],
        "2026-10-25",
    )
    assert "Lundi" in note
    assert "Brouillon" in note
    assert "Rien n'est envoyé" in note
    assert "SOC-9" in note
    assert compose_monday("fr", [], [], "2026-10-25") is None


def test_tax_and_month_end_calendar():
    assert first_working_day(2026, 10) == __import__("datetime").date(2026, 10, 1)
    state = {}
    notices = due_tax_notices(__import__("datetime").date(2026, 1, 10), state)
    keys = {item["date"].isoformat() for item in notices}
    assert keys == {"2026-01-20"}
    assert all(item["phase"] == "first" for item in notices)
    from feina_client.proactive import mark_tax_sent

    mark_tax_sent(state, "2026-01-20", "first")
    follow = due_tax_notices(__import__("datetime").date(2026, 1, 20), state)
    phases = {(item["date"].isoformat(), item["phase"]) for item in follow}
    assert ("2026-01-20", "followup") in phases
    month = compose_month("fr", __import__("datetime").date(2026, 10, 1), to="gestor@example.com", subject="AFSA", body="chiffres")
    assert "pas envoyé" in month
    assert "Répondez oui" in month
    assert compose_month("fr", __import__("datetime").date(2026, 10, 2), to="a", subject="b", body="c") is None


def test_morning_bundle_stops_at_two_messages():
    state = {}
    now = at(2026, 6, 1, 9, 0)  # Monday and the first working day
    night = {
        "confirmed_write": True,
        "figures_final": True,
        "outcome": "verified_match",
        "business_date": "2026-05-31",
        "failed_debits": [],
    }
    body = morning_bundle(
        state,
        lang="fr",
        now=now,
        enabled={"daily": True, "monday": True, "month_end": True, "tax": False},
        night=night,
        changes=["card: 1 → 2"],
        gestor_to="gestor@example.com",
        gestor_subject="AFSA",
        gestor_body="chiffres",
        when_clean=True,
    )
    assert body.count("AFSA Ingresos") == 1
    assert "Lundi" in body
    assert "Fin de mois" not in body and "pas envoyé" not in body
