"""Minimal transactional templates: plain `.format`, no Jinja.

ponytail: ceiling is ~2 simple templates; adopt Jinja when templates need
loops/conditionals or shared layouts.
"""

from __future__ import annotations

from src.email.base import EmailMessage


def invitation(to: str, *, workspace_name: str, invite_url: str) -> EmailMessage:
    text = (
        f"You've been invited to join {workspace_name}.\n\nAccept your invitation:\n{invite_url}\n"
    )
    html = (
        f"<p>You've been invited to join <strong>{workspace_name}</strong>.</p>"
        f'<p><a href="{invite_url}">Accept your invitation</a></p>'
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
        text_body=f"Reset your password:\n{reset_url}\n",
        html_body=f'<p><a href="{reset_url}">Reset your password</a></p>',
    )
