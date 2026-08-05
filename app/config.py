from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    airdcpp_url: str = "http://localhost:5600"
    airdcpp_user: str = ""
    airdcpp_pass: SecretStr = SecretStr("")

    bridge_api_key: SecretStr = SecretStr("")
    bridge_username: str = ""
    bridge_password: SecretStr = SecretStr("")
    allow_insecure: bool = False

    tmdb_api_key: SecretStr = SecretStr("")
    data_dir: Path = Path("/app/data")
    save_path: str = "/downloads"
    download_categories: str = "radarr,sonarr,radarr4k,sonarr4k"
    public_url: str = ""
    completed_ratio: float = Field(default=1.5, ge=0)
    allow_file_delete: bool = False

    search_timeout: float = Field(default=10.0, ge=2.0, le=60.0)
    search_poll_interval: float = Field(default=1.0, ge=0.1, le=10.0)
    search_stable_cycles: int = Field(default=2, ge=1, le=10)
    search_max_results: int = Field(default=1000, ge=1, le=5000)
    search_cache_ttl: int = Field(default=300, ge=0, le=86400)
    search_negative_cache_ttl: int = Field(default=30, ge=0, le=3600)
    search_cache_size: int = Field(default=256, ge=1, le=10000)
    search_min_accepted_results: int = Field(default=5, ge=1, le=100)
    search_max_variants: int = Field(default=4, ge=1, le=20)
    airdcpp_max_active_searches: int = Field(default=1, ge=1, le=8)
    log_level: str = "INFO"
    testing: bool = False

    @field_validator("airdcpp_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("save_path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        value = value.replace("\\", "/")
        return value.rstrip("/") or "/"

    @field_validator("download_categories")
    @classmethod
    def normalize_categories(cls, value: str) -> str:
        categories = []
        for raw in value.split(","):
            category = raw.strip().lower()
            if not category or category in categories:
                continue
            if not category.replace("-", "").replace("_", "").isalnum():
                raise ValueError("DOWNLOAD_CATEGORIES contiene una categoría no válida")
            categories.append(category)
        if not categories:
            raise ValueError("DOWNLOAD_CATEGORIES debe incluir al menos una categoría")
        return ",".join(categories)

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(self.download_categories.split(","))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bridge.db"

    def validate_runtime(self) -> None:
        if self.testing:
            return
        missing = []
        if not self.airdcpp_user:
            missing.append("AIRDCPP_USER")
        if not self.airdcpp_pass.get_secret_value():
            missing.append("AIRDCPP_PASS")
        if not self.allow_insecure:
            if not self.bridge_api_key.get_secret_value():
                missing.append("BRIDGE_API_KEY")
            if not self.bridge_username:
                missing.append("BRIDGE_USERNAME")
            if not self.bridge_password.get_secret_value():
                missing.append("BRIDGE_PASSWORD")
        if missing:
            raise ValueError("Faltan variables obligatorias: " + ", ".join(missing))


@lru_cache
def get_settings() -> Settings:
    return Settings()
