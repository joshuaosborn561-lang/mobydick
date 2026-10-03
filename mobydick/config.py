"""Environment-backed settings. Secrets stay in env vars, never in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    getleads_api_key: str
    getleads_endpoint: str
    email_waterfall_url: str
    email_waterfall_client_tag: str
    leadmagic_api_key: str
    leadmagic_endpoint: str
    youtube_api_key: str
    taddy_user_id: str
    taddy_api_key: str
    taddy_endpoint: str
    apify_api_key: str
    apify_actor: str
    anthropic_api_key: str
    openai_api_key: str

    @property
    def exclude_dir(self) -> Path:
        return self.data_dir / "exclude"

    @property
    def deliveries_dir(self) -> Path:
        return self.data_dir / "deliveries"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def dossiers_dir(self) -> Path:
        return self.data_dir / "dossiers"


def load_settings() -> Settings:
    raw = _env("MOBYDICK_DATA_DIR", "data")
    data_dir = Path(raw)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    return Settings(
        data_dir=data_dir,
        getleads_api_key=_env("GETLEADS_API_KEY"),
        getleads_endpoint=_env("GETLEADS_ENDPOINT", "https://app.getleads.io/api/mcp"),
        email_waterfall_url=_env(
            "EMAIL_WATERFALL_MCP_URL",
            "https://email-waterfall-production-021b.up.railway.app/mcp",
        ),
        email_waterfall_client_tag=_env("EMAIL_WATERFALL_CLIENT_TAG", "salesglider"),
        leadmagic_api_key=_env("LEADMAGIC_API_KEY"),
        leadmagic_endpoint=_env("LEADMAGIC_ENDPOINT", "https://api.leadmagic.io"),
        youtube_api_key=_env("YOUTUBE_API_KEY"),
        taddy_user_id=_env("TADDY_USER_ID"),
        taddy_api_key=_env("TADDY_API_KEY"),
        taddy_endpoint=_env("TADDY_ENDPOINT", "https://api.taddy.org"),
        apify_api_key=_env("APIFY_API_KEY"),
        apify_actor=_env("APIFY_ACTOR", "harvestapi~linkedin-profile-posts"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        openai_api_key=_env("OPENAI_API_KEY"),
    )


settings = load_settings()
