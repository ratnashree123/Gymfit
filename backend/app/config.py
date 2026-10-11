"""Application settings, loaded from the .env file."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GymFit"
    app_env: str = "development"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str
    db_password: str
    db_name: str = "gymfit"

    secret_key: str
    access_token_expire_minutes: int = 60

    frontend_origins: str = "http://127.0.0.1:5500,http://localhost:5500"
    gym_timezone: str = "Asia/Kolkata"

    # Only used by the one-time create_admin script.
    first_admin_name: str = "Gym Admin"
    first_admin_email: str | None = None
    first_admin_password: str | None = None

    # extra="ignore": unknown keys in .env will not crash the app.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_long(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return value

    @property
    def cors_origins(self) -> list[str]:
        """Turn the comma-separated string into a list."""
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Create the settings object once and reuse it."""
    return Settings()
