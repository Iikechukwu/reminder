"""Builds the reminder email text: LLM draft if available, else the template."""
import logging

from app import llm

log = logging.getLogger("reminder.reminders")


def render_template(name: str, starts_at) -> tuple[str, str]:
    when = starts_at.strftime("%A %d %B %Y at %H:%M UTC")
    subject = "Reminder: your upcoming booking"
    body = (
        f"Hi {name},\n\n"
        f"This is a reminder that your booking starts on {when}.\n\n"
        "If you can no longer make it, please cancel so we can free the slot.\n"
    )
    return subject, body


def compose_reminder(booking: dict, settings, client=None) -> tuple[str, str]:
    """Returns (subject, body) for this booking. Never raises because of the LLM."""
    subject, body = render_template(booking["customer_name"], booking["starts_at"])
    client = client or llm.build_client(settings.llm_mode)
    if client is None:
        return subject, body
    draft = llm.draft_body(
        client, booking["customer_name"], booking["starts_at"], settings.llm_timeout_seconds
    )
    if draft is None:
        log.info("using fallback template")
        return subject, body
    return subject, draft
