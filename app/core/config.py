from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    database_url: str
    jwt_secret_key: str
    access_token_expire_minutes: int
    max_profiles_per_organization: int

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./saas_gbp.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    settings = Settings(
        app_name=os.getenv("APP_NAME", "SaaS GBP API"),
        environment=os.getenv("ENVIRONMENT", "development"),
        database_url=database_url,
        jwt_secret_key=os.getenv(
            "JWT_SECRET_KEY", "development-only-change-this-secret-key"
        ),
        access_token_expire_minutes=int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        ),
        max_profiles_per_organization=int(
            os.getenv("MAX_PROFILES_PER_ORGANIZATION", "3")
        ),
    )
    if settings.is_production and settings.jwt_secret_key.startswith("development-"):
        raise RuntimeError("JWT_SECRET_KEY must be configured in production")
    if settings.access_token_expire_minutes <= 0:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than zero")
    return settings
