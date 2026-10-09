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


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < 0:
        return default
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    getleads_api_key: str
    getleads_endpoint: str
    email_waterfall_url: str
    email_waterfall_client_tag: str
    youtube_api_key: str
    taddy_user_id: str
    taddy_api_key: str
    taddy_endpoint: str
    apify_api_key: str
    apify_actor: str
    anthropic_api_key: str
    openai_api_key: str
    email_waterfall_approve_cost_usd: float = 0.25
    email_waterfall_run_ceiling_usd: float = 25.0

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
        youtube_api_key=_env("YOUTUBE_API_KEY"),
        taddy_user_id=_env("TADDY_USER_ID"),
        taddy_api_key=_env("TADDY_API_KEY"),
        taddy_endpoint=_env("TADDY_ENDPOINT", "https://api.taddy.org"),
        apify_api_key=_env("APIFY_API_KEY"),
        apify_actor=_env("APIFY_ACTOR", "harvestapi~linkedin-profile-posts"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        openai_api_key=_env("OPENAI_API_KEY"),
        email_waterfall_approve_cost_usd=_env_float("EMAIL_WATERFALL_APPROVE_COST_USD", 0.25),
        email_waterfall_run_ceiling_usd=_env_float("EMAIL_WATERFALL_RUN_CEILING_USD", 25.0),
    )


settings = load_settings()
