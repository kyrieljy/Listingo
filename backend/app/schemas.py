from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_name: str
    mime_type: str
    url: str
    width: int
    height: int
    byte_size: int
    created_at: datetime


class GenerationJobCreate(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=3)
    platform: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=80)
    aspect_ratio: str
    selling_points: str = Field(min_length=1, max_length=4000)
    product_name: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=200)
    specifications: str = Field(default="", max_length=1000)
    sku_info: str = Field(default="", max_length=1000)
    accessories: str = Field(default="", max_length=1000)
    certifications: str = Field(default="", max_length=1000)
    target_audience: str = Field(default="", max_length=1000)
    brand_style: str = Field(default="", max_length=2000)
    mode: Literal["smart", "custom"] = "smart"
    count: int = Field(default=7, ge=7, le=12)
    custom_counts: "CustomImageCounts | None" = None
    model_preference: Literal["fidelity", "layout"] = "fidelity"
    dry_run: bool = True

    @field_validator("aspect_ratio")
    @classmethod
    def validate_ratio(cls, value: str) -> str:
        if value not in ALLOWED_RATIOS:
            raise ValueError(f"非法比例：{value}")
        return value

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("商品图不能重复")
        return value

    @model_validator(mode="after")
    def validate_custom_allocation(self) -> "GenerationJobCreate":
        if self.mode == "custom":
            if self.custom_counts is None:
                raise ValueError("自定义配置必须提供各类型图片数量")
            if self.custom_counts.total != self.count:
                raise ValueError("自定义配置各类型数量之和必须等于生成数量")
        return self


class CustomImageCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    white_background: int = Field(default=1, ge=0, le=4)
    scene: int = Field(default=2, ge=0, le=4)
    selling_point: int = Field(default=2, ge=0, le=4)
    other: int = Field(default=2, ge=0, le=4)

    @property
    def total(self) -> int:
        return self.white_background + self.scene + self.selling_point + self.other


class CopywritingAssistCreate(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=3)
    platform: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=80)
    selling_points: str = Field(default="", max_length=4000)
    dry_run: bool = True


class CopywritingAssistOut(BaseModel):
    selling_points: str
    dry_run: bool
    provider_code: str | None = None


VIDEO_TYPES = {
    "痛点解决",
    "UGC 种草",
    "达人口播",
    "测评对比",
    "短剧搞笑带货",
    "视觉展示",
    "反转剧情",
    "清单榜单推荐",
}


class VideoJobCreate(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=3)
    platform: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    country: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=80)
    aspect_ratio: str = "9:16"
    selling_points: str = Field(default="", max_length=6000)
    product_name: str = Field(default="", max_length=200)
    target_audience: str = Field(default="", max_length=1000)
    video_types: list[str] = Field(min_length=1, max_length=8)
    duration: int = Field(default=15, ge=5, le=15)
    resolution: str = Field(default="1080p", max_length=40)
    generate_audio: bool = True
    camera_fixed: bool = False
    watermark: bool = False
    dry_run: bool = True

    @field_validator("aspect_ratio")
    @classmethod
    def validate_video_ratio(cls, value: str) -> str:
        if value not in ALLOWED_RATIOS:
            raise ValueError(f"非法比例：{value}")
        return value

    @field_validator("asset_ids")
    @classmethod
    def unique_video_assets(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("商品图不能重复")
        return value

    @field_validator("video_types")
    @classmethod
    def validate_video_types(cls, value: list[str]) -> list[str]:
        unique = []
        for item in value:
            if item not in VIDEO_TYPES:
                raise ValueError(f"不支持的视频类型：{item}")
            if item not in unique:
                unique.append(item)
        return unique


class VideoCopywritingAssistCreate(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=3)
    platform: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    country: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=80)
    selling_points: str = Field(default="", max_length=6000)
    video_types: list[str] = Field(default_factory=lambda: ["UGC 种草"], max_length=8)
    dry_run: bool = True


class VideoCopywritingAssistOut(BaseModel):
    selling_points: str
    dry_run: bool
    provider_code: str | None = None


class VideoVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_version_id: str | None
    version_no: int
    instruction: str
    url: str
    remote_url: str
    created_at: datetime


class VideoItemOut(BaseModel):
    id: str
    index: int
    video_type: str
    status: str
    provider_id: str | None
    provider_task_id: str | None
    error: str | None
    prompt_text: str
    script_markdown: str
    current_version_id: str | None
    versions: list[VideoVersionOut] = Field(default_factory=list)


class VideoJobOut(BaseModel):
    id: str
    status: str
    dry_run: bool
    progress: int
    count: int
    params: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: list[VideoItemOut] = Field(default_factory=list)


class GenerationVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_version_id: str | None
    version_no: int
    instruction: str
    url: str
    created_at: datetime


class GenerationItemOut(BaseModel):
    id: str
    index: int
    route_symbol: str
    image_type: str
    status: str
    provider_id: str | None
    error: str | None
    current_version_id: str | None
    versions: list[GenerationVersionOut]


class GenerationJobOut(BaseModel):
    id: str
    status: str
    dry_run: bool
    progress: int
    count: int
    params: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: list[GenerationItemOut] = Field(default_factory=list)


class GenerationVersionCreate(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)


class ProviderUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=5, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: bool | None = None
    is_default: bool | None = None
    is_fallback: bool | None = None
    api_key: str | None = Field(default=None, min_length=4, max_length=1000)
    resolution: str | None = None
    size: str | None = None
    quality: str | None = None
    format: str | None = None
    compression: int | None = Field(default=None, ge=0, le=100)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)


class ProviderOut(BaseModel):
    id: str
    code: str
    label: str
    capability: str
    adapter: str
    base_url: str
    model_name: str
    enabled: bool
    is_default: bool
    is_fallback: bool
    has_api_key: bool
    api_key_masked: str | None
    config: dict[str, Any]
    updated_at: datetime


class ProviderTestOut(BaseModel):
    ok: bool
    latency_ms: int
    message: str


class PromptVersionCreate(BaseModel):
    content: str = Field(min_length=20)
    change_note: str = Field(default="", max_length=500)


class WorkflowVersionCreate(BaseModel):
    graph: dict[str, Any]
    change_note: str = Field(default="", max_length=500)
