from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "970:600", "1464:600", "600:450"}
VIDEO_ALLOWED_SIZES = {"1:1", "3:4", "4:3", "9:16", "16:9", "21:9", "landscape", "portrait"}
VIDEO_ALLOWED_RESOLUTIONS = {"720p", "1080p"}
A_PLUS_DETAIL_RATIOS = {"1:1", "3:4", "9:16", "16:9"}
A_PLUS_AMAZON_STANDARD_RATIO = "970:600"
A_PLUS_AMAZON_ADVANCED_WEB_RATIO = "1464:600"
A_PLUS_AMAZON_ADVANCED_MOBILE_RATIO = "600:450"
A_PLUS_OUTPUT_MODES = {
    "detail",
    "amazon_aplus_standard",
    "amazon_aplus_advanced_web",
    "amazon_aplus_advanced_mobile",
}
A_PLUS_ADVANCED_MODES = {"amazon_aplus_advanced_web", "amazon_aplus_advanced_mobile"}
A_PLUS_MODULE_TOTAL_LIMIT = 12
A_PLUS_MODULES = {
    "商品主视觉",
    "卖点拆解",
    "生活场景",
    "全方位展示",
    "情绪氛围",
    "品质细看",
    "品牌心智",
    "规格指南",
    "效果呈现",
    "产品资料",
    "制造揭秘",
    "开箱清单",
    "款式矩阵",
    "材质解析",
    "服务承诺",
    "使用攻略",
}


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
    asset_ids: list[str] = Field(min_length=1, max_length=6)
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
    asset_ids: list[str] = Field(default_factory=list, max_length=6)
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
    asset_ids: list[str] = Field(min_length=1, max_length=6)
    platform: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    country: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=80)
    aspect_ratio: str = "9:16"
    selling_points: str = Field(default="", max_length=6000)
    product_name: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=200)
    target_audience: str = Field(default="", max_length=1000)
    video_types: list[str] = Field(min_length=1, max_length=8)
    duration: int = Field(default=15, ge=5, le=15)
    resolution: str = Field(default="1080p", max_length=40)
    dry_run: bool = True

    @field_validator("aspect_ratio")
    @classmethod
    def validate_video_ratio(cls, value: str) -> str:
        if value not in VIDEO_ALLOWED_SIZES:
            raise ValueError(f"非法视频画面 size：{value}")
        return value

    @field_validator("resolution")
    @classmethod
    def validate_video_resolution(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VIDEO_ALLOWED_RESOLUTIONS:
            raise ValueError(f"非法视频清晰度：{value}")
        return normalized

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
    asset_ids: list[str] = Field(default_factory=list, max_length=6)
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


class AplusOutputTarget(BaseModel):
    mode: Literal["detail", "amazon_aplus_standard", "amazon_aplus_advanced_web", "amazon_aplus_advanced_mobile"]
    aspect_ratio: str

    @model_validator(mode="after")
    def validate_mode_ratio(self) -> "AplusOutputTarget":
        expected = {
            "amazon_aplus_standard": {A_PLUS_AMAZON_STANDARD_RATIO},
            "amazon_aplus_advanced_web": {A_PLUS_AMAZON_ADVANCED_WEB_RATIO},
            "amazon_aplus_advanced_mobile": {A_PLUS_AMAZON_ADVANCED_MOBILE_RATIO},
            "detail": A_PLUS_DETAIL_RATIOS,
        }[self.mode]
        if self.aspect_ratio not in expected:
            raise ValueError(f"A+ 输出模式 {self.mode} 不支持比例 {self.aspect_ratio}")
        return self


def validate_aplus_output_target_selection(output_targets: list[AplusOutputTarget], platform: str | None = None) -> None:
    seen = {(target.mode, target.aspect_ratio) for target in output_targets}
    if len(seen) != len(output_targets):
        raise ValueError("A+ 输出规格不能重复")

    modes = {target.mode for target in output_targets}
    if platform is not None and any(mode != "detail" for mode in modes) and platform != "亚马逊":
        raise ValueError("普通 A+ 和高级 A+ 只支持亚马逊平台")

    if modes == {"detail"}:
        if len(output_targets) != 1:
            raise ValueError("1:1、3:4、9:16、16:9 每次只能选择一个")
        return

    if modes == {"amazon_aplus_standard"}:
        if len(output_targets) != 1:
            raise ValueError("普通 A+ 每次只能选择一个 970:600 输出规格")
        return

    if modes.issubset(A_PLUS_ADVANCED_MODES):
        if not output_targets:
            raise ValueError("高级 A+ 至少选择 Web 或移动端中的一个")
        return

    raise ValueError("普通 A+、高级 A+、1:1、3:4、9:16、16:9 每次只能选择一个")


class AplusModuleSelection(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1, le=A_PLUS_MODULE_TOTAL_LIMIT)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if value not in A_PLUS_MODULES:
            raise ValueError(f"不支持的详情页模块：{value}")
        return value


class AplusPlanJobCreate(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=6)
    platform: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=80)
    product_info: str = Field(default="", max_length=6000)
    category: str = Field(default="", max_length=200)
    module_selections: list[AplusModuleSelection] | None = Field(default=None, max_length=A_PLUS_MODULE_TOTAL_LIMIT)
    selected_modules: list[str] | None = Field(default=None, max_length=A_PLUS_MODULE_TOTAL_LIMIT)
    output_targets: list[AplusOutputTarget] = Field(min_length=1, max_length=8)
    dry_run: bool = True

    @field_validator("asset_ids")
    @classmethod
    def unique_aplus_assets(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("商品图不能重复")
        return value

    @field_validator("selected_modules")
    @classmethod
    def validate_modules(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unique: list[str] = []
        for item in value:
            if item not in A_PLUS_MODULES:
                raise ValueError(f"不支持的详情页模块：{item}")
            if item not in unique:
                unique.append(item)
        return unique

    @model_validator(mode="after")
    def validate_platform_targets(self) -> "AplusPlanJobCreate":
        if not self.module_selections:
            if not self.selected_modules:
                raise ValueError("请至少选择 1 个详情页模块")
            self.module_selections = [AplusModuleSelection(name=name, count=1) for name in self.selected_modules]
        seen: set[str] = set()
        unique: list[AplusModuleSelection] = []
        for selection in self.module_selections:
            if selection.name in seen:
                raise ValueError(f"详情页模块不能重复配置：{selection.name}")
            seen.add(selection.name)
            unique.append(selection)
        self.module_selections = unique
        self.selected_modules = [selection.name for selection in unique]
        total = self.module_total
        if total < 1:
            raise ValueError("请至少生成 1 张详情页模块")
        if total > A_PLUS_MODULE_TOTAL_LIMIT:
            raise ValueError(f"详情页模块最多生成 {A_PLUS_MODULE_TOTAL_LIMIT} 张")
        validate_aplus_output_target_selection(self.output_targets, self.platform)
        return self

    @property
    def module_total(self) -> int:
        return sum(selection.count for selection in (self.module_selections or []))


class AplusGenerationJobCreate(BaseModel):
    plan_job_id: str
    module_item_ids: list[str] = Field(default_factory=list, max_length=A_PLUS_MODULE_TOTAL_LIMIT)
    output_targets: list[AplusOutputTarget] = Field(min_length=1, max_length=8)
    dry_run: bool = True

    @model_validator(mode="after")
    def validate_output_targets(self) -> "AplusGenerationJobCreate":
        validate_aplus_output_target_selection(self.output_targets)
        return self


class AplusVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_version_id: str | None
    version_no: int
    instruction: str
    url: str
    created_at: datetime


class AplusItemOut(BaseModel):
    id: str
    index: int
    module_index: int
    module_name: str
    output_mode: str
    aspect_ratio: str
    image_prompt: str
    copy_requirements: str
    prompt_text: str
    status: str
    provider_id: str | None
    provider_task_id: str | None
    source_web_item_id: str | None
    error: str | None
    current_version_id: str | None
    versions: list[AplusVersionOut] = Field(default_factory=list)


class AplusJobOut(BaseModel):
    id: str
    job_type: str
    status: str
    dry_run: bool
    progress: int
    count: int
    params: dict[str, Any]
    source_plan_job_id: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: list[AplusItemOut] = Field(default_factory=list)


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
    prompt_text: str
    status: str
    provider_id: str | None
    provider_task_id: str | None
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
    instruction: str = Field(max_length=2000)


class ImageTextBox(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class ImageTextLineOut(BaseModel):
    id: str
    index: int
    text: str
    confidence: float = Field(ge=0, le=1)
    bbox: ImageTextBox


class ImageTextOcrOut(BaseModel):
    lines: list[ImageTextLineOut] = Field(default_factory=list)
    warning: str | None = None


class ImageTextEditLine(BaseModel):
    id: str | None = Field(default=None, max_length=80)
    index: int = Field(ge=0)
    original_text: str = Field(default="", max_length=500)
    text: str = Field(default="", max_length=500)
    bbox: ImageTextBox | None = None


class ImageTextVersionCreate(BaseModel):
    lines: list[ImageTextEditLine] = Field(min_length=1, max_length=80)


class ProviderUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=5, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: bool | None = None
    is_default: bool | None = None
    is_fallback: bool | None = None
    route_roles: dict[str, str | None] | None = None
    api_key: str | None = Field(default=None, min_length=4, max_length=1000)
    resolution: str | None = None
    size: str | None = None
    quality: str | None = None
    style: str | None = None
    format: str | None = None
    response_format: str | None = None
    compression: int | None = Field(default=None, ge=0, le=100)
    timeout_seconds: int | None = Field(default=None, ge=5, le=1800)
    poll_interval_seconds: int | None = Field(default=None, ge=0, le=120)
    max_reference_images: int | None = Field(default=None, ge=0, le=14)
    parameter_values: dict[str, Any] | None = None


class ProviderRouteChainUpdate(BaseModel):
    provider_codes: list[str] = Field(default_factory=list, max_length=5)


class WorkspaceConfigOut(BaseModel):
    max_upload_bytes: int
    max_batch_tasks: int
    max_batch_item_assets: int
    max_active_batch_items: int
    max_provider_concurrency: int


class BatchItemCreate(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=6)
    name: str = Field(default="", max_length=200)
    selling_points: str = Field(default="", max_length=6000)
    overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_ids")
    @classmethod
    def unique_batch_assets(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("商品图不能重复")
        return value


class BatchJobCreate(BaseModel):
    business_type: Literal["suite", "aplus"]
    global_params: dict[str, Any] = Field(default_factory=dict)
    items: list[BatchItemCreate] = Field(min_length=1, max_length=100)
    notification_config: dict[str, Any] = Field(default_factory=dict)


class BatchItemOut(BaseModel):
    id: str
    index: int
    name: str
    status: str
    thumbnail_url: str | None = None
    completed_image_count: int = 0
    failed_image_count: int = 0
    total_image_count: int = 0
    params: dict[str, Any]
    asset_ids: list[str]
    generation_job_id: str | None
    aplus_plan_job_id: str | None
    aplus_generation_job_id: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    generation_job: GenerationJobOut | None = None
    aplus_plan_job: AplusJobOut | None = None
    aplus_generation_job: AplusJobOut | None = None


class BatchJobOut(BaseModel):
    id: str
    user_id: str | None = None
    business_type: str
    status: str
    global_params: dict[str, Any]
    total_count: int
    completed_count: int
    failed_count: int
    progress: int
    notification_config: dict[str, Any]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[BatchItemOut] = Field(default_factory=list)


class BatchValidationFixturesCreate(BaseModel):
    business_type: Literal["suite", "aplus"]


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
    route_roles: dict[str, str]
    provider_group: str | None = None
    provider_group_label: str | None = None
    operation: str | None = None
    supports_custom_size: bool = False
    supports_exact_custom_size: bool = False
    supports_edit: bool = False
    pricing: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    has_api_key: bool
    api_key_masked: str | None
    config: dict[str, Any]
    updated_at: datetime


class ProviderTestOut(BaseModel):
    ok: bool
    latency_ms: int
    message: str
    status: Literal["ok", "failed", "unknown"] = "ok"


class ProviderGroupOut(BaseModel):
    key: str
    label: str
    website: str
    provider_count: int = 0
    enabled_count: int = 0
    keyed_count: int = 0


class PromptVersionCreate(BaseModel):
    content: str = Field(min_length=20)
    change_note: str = Field(default="", max_length=500)


class PromptTestRunCreate(BaseModel):
    test_type: Literal["llm_output", "full_chain"]
    prompt_content: str = Field(min_length=20, max_length=2 * 1024 * 1024)
    inputs: dict[str, Any] = Field(default_factory=dict)


class PromptTestRunOut(BaseModel):
    id: str
    prompt_id: str
    prompt_code: str
    test_type: str
    status: str
    progress: int
    prompt_content_sha256: str
    input_params: dict[str, Any]
    raw_output: str
    parsed_output: dict[str, Any]
    validation_errors: list[str]
    related_job_type: str | None
    related_job_id: str | None
    artifact_urls: list[str]
    provider_code: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowVersionCreate(BaseModel):
    graph: dict[str, Any]
    change_note: str = Field(default="", max_length=500)


class SmsSendCreate(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    purpose: Literal["login", "register", "reset_password", "change_phone", "admin"] = "login"


class SmsSendOut(BaseModel):
    ok: bool
    expires_in: int
    message: str
    debug_code: str | None = None


class SmsLoginCreate(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=4, max_length=12)
    mode: Literal["login", "register"] = "login"


class RegisterCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=6, max_length=128)
    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=4, max_length=12)


class PasswordLoginCreate(BaseModel):
    identifier: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=1, max_length=128)
    admin_code: str | None = Field(default=None, max_length=12)


class FirstPasswordCreate(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class AuthUserOut(BaseModel):
    id: str
    phone: str
    phone_masked: str
    username: str
    display_name: str
    email: str
    avatar_initials: str
    uid: str
    role: str
    status: str
    plan: str
    gender: str
    bio: str
    password_set: bool
    first_password_pending: bool
    last_login_at: datetime | None
    created_at: datetime
    feishu_webhook: str
    feishu_webhook_configured: bool


class AuthMeOut(BaseModel):
    user: AuthUserOut | None
    unread_count: int = 0


class AnalyticsEventCreate(BaseModel):
    session_id: str = Field(default="", max_length=80)
    event_name: str = Field(min_length=1, max_length=120)
    event_type: str = Field(default="click", max_length=40)
    surface: str = Field(default="", max_length=80)
    business_type: str = Field(default="", max_length=40)
    feature_key: str = Field(default="", max_length=80)
    platform: str = Field(default="", max_length=80)
    market: str = Field(default="", max_length=80)
    language: str = Field(default="", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    gender: str | None = Field(default=None, max_length=20)
    bio: str | None = Field(default=None, max_length=140)
    feishu_webhook: str | None = Field(default=None, max_length=512)


class FeishuWebhookTestCreate(BaseModel):
    """Webhook URL to probe. Empty means "fall back to the saved value"."""

    webhook: str = Field(default="", max_length=512)


class PasswordChangeCreate(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    next_password: str = Field(min_length=6, max_length=128)


class ChangePhoneStartCreate(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class ChangePhoneConfirmCreate(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=4, max_length=12)


class PlanPriceOut(BaseModel):
    id: str
    billing_cycle: str
    amount_cents: int | None
    currency: str
    price_label: str
    period_label: str


class PlanQuotaRuleOut(BaseModel):
    id: str
    action_key: str
    action_label: str
    unit: str
    monthly_limit: int | None
    cost_multiplier: int
    warning_threshold: int
    enabled: bool


class SubscriptionPlanOut(BaseModel):
    id: str
    code: str
    name: str
    description: str
    badge: str
    cta: str
    enabled: bool
    visible: bool
    is_internal: bool
    is_enterprise: bool
    features: list[str]
    contact_text: str
    contact_phone: str
    prices: list[PlanPriceOut]
    quota_rules: list[PlanQuotaRuleOut]
    sort_order: int


class QuotaRowOut(PlanQuotaRuleOut):
    used: int
    remaining: int | None
    period: str


class QuotaSummaryOut(BaseModel):
    plan: SubscriptionPlanOut
    period: str
    rows: list[QuotaRowOut]


class PaymentOrderCreate(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)
    billing_cycle: Literal["monthly", "yearly"] = "monthly"


class PaymentOrderOut(BaseModel):
    id: str
    order_no: str
    plan_code: str
    plan_name: str
    billing_cycle: str
    amount_cents: int | None
    currency: str
    status: str
    paid_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class NotificationOut(BaseModel):
    id: str
    category: str
    title: str
    body: str
    unread: bool
    metadata: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class AdminUserUpdate(BaseModel):
    role: Literal["user", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None
    plan_code: str | None = Field(default=None, max_length=40)


class AdminPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    badge: str | None = Field(default=None, max_length=80)
    cta: str | None = Field(default=None, max_length=80)
    visible: bool | None = None
    enabled: bool | None = None
    features: list[str] | None = None
    contact_text: str | None = None
    contact_phone: str | None = Field(default=None, max_length=32)


class AdminQuotaRuleUpdate(BaseModel):
    monthly_limit: int | None = Field(default=None, ge=0)
    cost_multiplier: int | None = Field(default=None, ge=1, le=100)
    warning_threshold: int | None = Field(default=None, ge=1, le=100)
    enabled: bool | None = None


class SmsSettingsUpdate(BaseModel):
    provider: Literal["aliyun", "aliyun_pnvs"] | None = None
    enabled: bool | None = None
    debug_mode: bool | None = None
    region_id: str | None = Field(default=None, max_length=80)
    sign_name: str | None = Field(default=None, max_length=120)
    login_template_code: str | None = Field(default=None, max_length=80)
    register_template_code: str | None = Field(default=None, max_length=80)
    change_phone_template_code: str | None = Field(default=None, max_length=80)
    admin_template_code: str | None = Field(default=None, max_length=80)
    access_key_id: str | None = Field(default=None, max_length=200)
    access_key_secret: str | None = Field(default=None, max_length=1000)
    code_ttl_seconds: int | None = Field(default=None, ge=60, le=1800)
    cooldown_seconds: int | None = Field(default=None, ge=10, le=600)
    daily_limit_per_phone: int | None = Field(default=None, ge=1, le=100)
    notify_template_code: str | None = Field(default=None, max_length=80)


class AdminNotificationBroadcastCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=4000)
    user_ids: list[str] = Field(default_factory=list, max_length=500)


class SensitiveWordCreate(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True
    note: str = Field(default="", max_length=500)

    @field_validator("term", "aliases")
    @classmethod
    def strip_terms(cls, value: list[str] | str) -> list[str] | str:
        if isinstance(value, str):
            return value.strip()
        return [item.strip() for item in value]


class SensitiveWordUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = Field(default=None, max_length=20)
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("term", "aliases")
    @classmethod
    def strip_terms(cls, value: list[str] | str | None) -> list[str] | str | None:
        if value is None:
            return value
        if isinstance(value, str):
            return value.strip()
        return [item.strip() for item in value]


class SensitiveWordSettingsUpdate(BaseModel):
    enabled: bool | None = None
    max_variants_per_word: int | None = Field(default=None, ge=1, le=1024)
    max_total_variants: int | None = Field(default=None, ge=1, le=1_000_000)
    max_snapshot_bytes: int | None = Field(default=None, ge=1024, le=100 * 1024 * 1024)


class SensitiveWordBulkCreate(BaseModel):
    terms: list[str] = Field(min_length=1, max_length=2000)
    enabled: bool = True
    note: str = Field(default="", max_length=500)
