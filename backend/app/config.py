"""Application configuration.

All runtime settings are read from environment variables (see ``.env.example``).
No secrets may ever be hard-coded in source (blueprint §82).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__

_BASE_DIR = Path(__file__).resolve().parent.parent  # backend/

#: The factory default. A production process must NEVER sign tokens with it:
#: the Windows launcher persists a random per-install key instead (see
#: installer/windows/run_supermarket.py :: persistent_secret).
DEFAULT_SECRET_KEY = "change-me-in-production-9f8e7d6c5b4a"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Supermarket System"
    #: Single source of truth is ``app.__version__``; keeping a second literal
    #: here is how /health ends up advertising a stale version.
    APP_VERSION: str = __version__
    ENVIRONMENT: str = "development"  # development | production

    # Database — SQLite is the default (ACID, single-file, offline-first).
    # For a central server the same URL can point to PostgreSQL.
    DATABASE_URL: str = f"sqlite:///{_BASE_DIR / 'data' / 'supermarket.db'}"

    # Security / Auth
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 hours

    @model_validator(mode="after")
    def _forbid_default_secret_in_production(self):
        """v3.7 — no usable default credential in production (§33).

        Every install must sign its tokens with its own key. Anyone who signs
        with the published factory default lets anybody forge an admin token.
        """
        if (self.ENVIRONMENT or "").lower() == "production" and self.SECRET_KEY == DEFAULT_SECRET_KEY:
            raise ValueError(
                "refusing to start: SECRET_KEY is the factory default in production. "
                "Set a unique SECRET_KEY (the Windows launcher persists one per install).")
        return self

    # CORS — the web panel origin (and any LAN terminals).
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173"

    # First-boot admin bootstrap (dev convenience; never used in production seeds).
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # External resolvers — optional. Enabled only when a source is configured.
    EXTERNAL_TIMEOUT_SECONDS: float = 8.0

    # Server binding (used by the launcher and reported by diagnostics/LAN check)
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Support-request relay (v1.7). Ticket delivery channel of the vendor; the
    # UI never names the transport. Owner may override via env / system_settings.
    SUPPORT_RELAY_URL: str = "https://botapi.rubika.ir/v3"
    SUPPORT_RELAY_TOKEN: str = "CDJFAE0BITPJAHSUTQNWIIZKSMPOTEYATQNHZVDZYBWMUMYISOIRVWVINHFSRXVF"
    SUPPORT_INBOX_ID: str = ""          # learned automatically from the relay feed
    SUPPORT_OWNER_USERNAME: str = "Khajavi8056"

    # Local media storage for downloaded product images (§21 — never hotlink)
    MEDIA_DIR: str = str(_BASE_DIR / "data" / "media")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        p = Path(self.DATABASE_URL.split("///")[-1]).parent if self.DATABASE_URL.startswith("sqlite:///") else _BASE_DIR / "data"
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
