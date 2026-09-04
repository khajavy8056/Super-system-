"""Application configuration.

All runtime settings are read from environment variables (see ``.env.example``).
No secrets may ever be hard-coded in source (blueprint §82).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Supermarket System"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"  # development | production

    # Database — SQLite is the default (ACID, single-file, offline-first).
    # For a central server the same URL can point to PostgreSQL.
    DATABASE_URL: str = f"sqlite:///{_BASE_DIR / 'data' / 'supermarket.db'}"

    # Security / Auth
    SECRET_KEY: str = "change-me-in-production-9f8e7d6c5b4a"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 hours

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
