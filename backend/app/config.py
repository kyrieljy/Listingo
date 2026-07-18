from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LISTINGO_", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str | None = None
    testing: bool = False
    global_dry_run: bool = True
    public_asset_base_url: str = ""
    max_upload_bytes: int = 15 * 1024 * 1024
    max_job_concurrency: int = Field(default=4, ge=1, le=8)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'listingo.sqlite3').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / ".secret_key"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.uploads_dir, self.results_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)
