"""Minimal transactional templates: plain f-strings, no Jinja.

ponytail: ceiling is ~2 simple templates; adopt Jinja when templates need
loops/conditionals or shared layouts.
"""

from __future__ import annotations

from html import escape

from src.email.base import EmailMessage  # noqa: E402


def invitation(
    to: str,
    *,
    workspace_name: str,
    invite_url: str,
    invited_by: str = "",
) -> EmailMessage:
    inviter = invited_by.strip()
    lead = (
        f"{inviter} has invited you" if inviter else "You've been invited"
    ) + f" to join the {workspace_name} workspace."
    text = (
        f"Hi there,\n\n{lead}\n\nAccept your invitation:\n{invite_url}\n\n"
        "If you weren't expecting this email, you can safely ignore it.\n"
    )
    if inviter:
        lead_html = (
            f"<strong>{escape(inviter)}</strong> has invited you to join "
            f"the <strong>{escape(workspace_name)}</strong> workspace."
        )
    else:
        lead_html = (
            f"You've been invited to join the <strong>{escape(workspace_name)}</strong> workspace."
        )
    html = (
        f"<p>Hi there,</p><p>{lead_html}</p>"
        f'<p><a href="{escape(invite_url, quote=True)}">Accept your invitation</a></p>'
        "<p>If you weren't expecting this email, you can safely ignore it.</p>"
    )
    return EmailMessage(
        to=to,
        subject=f"You're invited to {workspace_name}",
        text_body=text,
        html_body=html,
    )


def password_reset(to: str, *, reset_url: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Reset your password",
        text_body=(
            "Hi there,\n\nWe received a request to reset your password.\n\n"
            f"Choose a new password:\n{reset_url}\n\n"
            "If you didn't request this, you can safely ignore this email; "
            "your password won't change.\n"
        ),
        html_body=(
            "<p>Hi there,</p>"
            "<p>We received a request to reset your password.</p>"
            f'<p><a href="{escape(reset_url, quote=True)}">Choose a new password</a></p>'
            "<p>If you didn't request this, you can safely ignore this email; "
            "your password won't change.</p>"
        ),
    )
