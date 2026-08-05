from enum import StrEnum

from pydantic import BaseModel, Field


class DownloadState(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    REMOVED = "removed"


class SearchResult(BaseModel):
    release_id: str
    name: str
    size: int = Field(ge=0)
    tth: str | None = None
    item_type: str = "file"
    source_id: int | str | None = None
    query: str = ""
    published_at: int = Field(default=0, ge=0)
    availability: int = Field(default=1, ge=1)
    languages: list[str] = Field(default_factory=list)
    # ``name`` es el titulo que deben analizar los ARR. Estos campos conservan
    # la identidad real del elemento compartido cuando el titulo es sintetico.
    source_name: str | None = None
    source_path: str | None = None
    source_cid: str | None = None
    source_hub_url: str | None = None
    download_via_filelist: bool = False
    selected_files: list[dict[str, str | int]] = Field(default_factory=list)


class DownloadRecord(BaseModel):
    download_id: str
    release_id: str
    bundle_id: str | None = None
    category: str
    name: str
    size: int = 0
    state: DownloadState = DownloadState.QUEUED
    progress: float = 0.0
    downloaded: int = 0
    speed: int = 0
    eta: int = 8640000
    added_on: int
    completed_on: int = 0
