"""Project-owned configuration (demo: one message string).

The template `Settings` class is never edited per feature; project settings
live here as a separate `ProjectSettings` object (override with a
`DEMO_MESSAGE` env var or `.env` entry).
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", os.path.expanduser("~/.config/saas-template/.env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    demo_message: str = "hello from the project extension"


project_settings = ProjectSettings()
