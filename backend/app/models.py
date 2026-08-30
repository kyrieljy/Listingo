from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(Base, TimestampMixin):
    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(160), default="")
    display_name: Mapped[str] = mapped_column(String(120))
    avatar_initials: Mapped[str] = mapped_column(String(8), default="LI")
    uid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_set: Mapped[bool] = mapped_column(Boolean, default=False)
    first_password_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    gender: Mapped[str] = mapped_column(String(20), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    current_plan_code: Mapped[str] = mapped_column(String(40), default="free", index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base, TimestampMixin):
    __tablename__ = "user_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(80), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")


class LoginEvent(Base):
    __tablename__ = "login_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), default="", index=True)
    method: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    ip_address: Mapped[str] = mapped_column(String(80), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    event_name: Mapped[str] = mapped_column(String(120), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    surface: Mapped[str] = mapped_column(String(80), default="", index=True)
    business_type: Mapped[str] = mapped_column(String(40), default="", index=True)
    feature_key: Mapped[str] = mapped_column(String(80), default="", index=True)
    platform: Mapped[str] = mapped_column(String(80), default="", index=True)
    market: Mapped[str] = mapped_column(String(80), default="", index=True)
    language: Mapped[str] = mapped_column(String(80), default="", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    ip_address: Mapped[str] = mapped_column(String(80), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SmsConfig(Base, TimestampMixin):
    __tablename__ = "sms_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(40), default="aliyun")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    debug_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    region_id: Mapped[str] = mapped_column(String(80), default="cn-hangzhou")
    sign_name: Mapped[str] = mapped_column(String(120), default="")
    login_template_code: Mapped[str] = mapped_column(String(80), default="")
    register_template_code: Mapped[str] = mapped_column(String(80), default="")
    change_phone_template_code: Mapped[str] = mapped_column(String(80), default="")
    admin_template_code: Mapped[str] = mapped_column(String(80), default="")
    access_key_id: Mapped[str] = mapped_column(String(200), default="")
    encrypted_access_key_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_ttl_seconds: Mapped[int] = mapped_column(Integer, default=300)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    daily_limit_per_phone: Mapped[int] = mapped_column(Integer, default=10)


class SensitiveWordConfig(Base, TimestampMixin):
    __tablename__ = "sensitive_word_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    max_variants_per_word: Mapped[int] = mapped_column(Integer, default=256)
    max_total_variants: Mapped[int] = mapped_column(Integer, default=100_000)
    max_snapshot_bytes: Mapped[int] = mapped_column(Integer, default=10_485_760)


class SensitiveWord(Base, TimestampMixin):
    __tablename__ = "sensitive_word"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    term: Mapped[str] = mapped_column(String(120))
    normalized_term: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    note: Mapped[str] = mapped_column(Text, default="")


class SensitiveWordSnapshot(Base, TimestampMixin):
    __tablename__ = "sensitive_word_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    variant_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_bytes: Mapped[int] = mapped_column(Integer, default=0)


class SubscriptionPlan(Base, TimestampMixin):
    __tablename__ = "subscription_plan"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    badge: Mapped[str] = mapped_column(String(80), default="")
    cta: Mapped[str] = mapped_column(String(80), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    visible: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_enterprise: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    features_json: Mapped[str] = mapped_column(Text, default="[]")
    contact_text: Mapped[str] = mapped_column(Text, default="")
    contact_phone: Mapped[str] = mapped_column(String(32), default="")


class PlanPrice(Base, TimestampMixin):
    __tablename__ = "plan_price"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plan.id", ondelete="CASCADE"), index=True)
    billing_cycle: Mapped[str] = mapped_column(String(20), index=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(12), default="CNY")
    price_label: Mapped[str] = mapped_column(String(80), default="")
    period_label: Mapped[str] = mapped_column(String(40), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class PlanQuotaRule(Base, TimestampMixin):
    __tablename__ = "plan_quota_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plan.id", ondelete="CASCADE"), index=True)
    action_key: Mapped[str] = mapped_column(String(60), index=True)
    action_label: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(40), default="次")
    monthly_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_multiplier: Mapped[int] = mapped_column(Integer, default=1)
    warning_threshold: Mapped[int] = mapped_column(Integer, default=80)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class UserSubscription(Base, TimestampMixin):
    __tablename__ = "user_subscription"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plan.id"), index=True)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly")
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    source_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class PaymentOrder(Base, TimestampMixin):
    __tablename__ = "payment_order"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plan.id"), index=True)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly")
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(12), default="CNY")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")


class QuotaLedger(Base):
    __tablename__ = "quota_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    action_key: Mapped[str] = mapped_column(String(60), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="reserved", index=True)
    ref_type: Mapped[str] = mapped_column(String(40), default="", index=True)
    ref_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base, TimestampMixin):
    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40), default="system", index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    unread: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Provider(Base, TimestampMixin):
    __tablename__ = "provider"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120))
    capability: Mapped[str] = mapped_column(String(20), index=True)
    adapter: Mapped[str] = mapped_column(String(50))
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")


class Prompt(Base, TimestampMixin):
    __tablename__ = "prompt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan", foreign_keys="PromptVersion.prompt_id"
    )


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "prompt_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    change_note: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[Prompt] = relationship(back_populates="versions", foreign_keys=[prompt_id])


class PromptTestRun(Base, TimestampMixin):
    __tablename__ = "prompt_test_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt.id", ondelete="CASCADE"), index=True)
    prompt_code: Mapped[str] = mapped_column(String(80), index=True)
    test_type: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    prompt_content_snapshot: Mapped[str] = mapped_column(Text)
    prompt_content_sha256: Mapped[str] = mapped_column(String(64))
    input_params_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_output: Mapped[str] = mapped_column(Text, default="")
    parsed_output_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_errors_json: Mapped[str] = mapped_column(Text, default="[]")
    related_job_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    artifact_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    provider_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[Prompt] = relationship(foreign_keys=[prompt_id])


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflow"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    versions: Mapped[list[WorkflowVersion]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", foreign_keys="WorkflowVersion.workflow_id"
    )


class WorkflowVersion(Base, TimestampMixin):
    __tablename__ = "workflow_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    graph_json: Mapped[str] = mapped_column(Text)
    change_note: Mapped[str] = mapped_column(Text, default="")
    workflow: Mapped[Workflow] = relationship(back_populates="versions", foreign_keys=[workflow_id])


class Asset(Base, TimestampMixin):
    __tablename__ = "asset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(80))
    file_path: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(1000))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))

class GenerationJob(Base, TimestampMixin):
    __tablename__ = "generation_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    params_json: Mapped[str] = mapped_column(Text)
    asset_ids_json: Mapped[str] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_version.id"))
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_version.id"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[GenerationItem]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="GenerationItem.index"
    )


class GenerationItem(Base, TimestampMixin):
    __tablename__ = "generation_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("generation_job.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    route_symbol: Mapped[str] = mapped_column(String(12), default="#@")
    image_type: Mapped[str] = mapped_column(String(120))
    prompt_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("provider.id"), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job: Mapped[GenerationJob] = relationship(back_populates="items")
    versions: Mapped[list[GenerationVersion]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="GenerationVersion.version_no"
    )


class GenerationVersion(Base, TimestampMixin):
    __tablename__ = "generation_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("generation_item.id", ondelete="CASCADE"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer)
    instruction: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(1000))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    item: Mapped[GenerationItem] = relationship(back_populates="versions")


class VideoJob(Base, TimestampMixin):
    __tablename__ = "video_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    params_json: Mapped[str] = mapped_column(Text)
    asset_ids_json: Mapped[str] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_version.id"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[VideoItem]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="VideoItem.index"
    )


class VideoItem(Base, TimestampMixin):
    __tablename__ = "video_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("video_job.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    video_type: Mapped[str] = mapped_column(String(120))
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    script_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("provider.id"), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job: Mapped[VideoJob] = relationship(back_populates="items")
    versions: Mapped[list[VideoVersion]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="VideoVersion.version_no"
    )


class VideoVersion(Base, TimestampMixin):
    __tablename__ = "video_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("video_item.id", ondelete="CASCADE"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer)
    instruction: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    url: Mapped[str] = mapped_column(String(1000))
    remote_url: Mapped[str] = mapped_column(String(1000), default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    item: Mapped[VideoItem] = relationship(back_populates="versions")


class AplusJob(Base, TimestampMixin):
    __tablename__ = "aplus_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(30), default="plan", index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    params_json: Mapped[str] = mapped_column(Text)
    asset_ids_json: Mapped[str] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_version.id"))
    source_plan_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[AplusItem]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="AplusItem.index"
    )


class AplusItem(Base, TimestampMixin):
    __tablename__ = "aplus_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("aplus_job.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    module_index: Mapped[int] = mapped_column(Integer)
    module_name: Mapped[str] = mapped_column(String(160))
    output_mode: Mapped[str] = mapped_column(String(60), default="plan")
    aspect_ratio: Mapped[str] = mapped_column(String(40), default="")
    image_prompt: Mapped[str] = mapped_column(Text, default="")
    copy_requirements: Mapped[str] = mapped_column(Text, default="")
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("provider.id"), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_web_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job: Mapped[AplusJob] = relationship(back_populates="items")
    versions: Mapped[list[AplusVersion]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="AplusVersion.version_no"
    )


class AplusVersion(Base, TimestampMixin):
    __tablename__ = "aplus_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("aplus_item.id", ondelete="CASCADE"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer)
    instruction: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    url: Mapped[str] = mapped_column(String(1000))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    item: Mapped[AplusItem] = relationship(back_populates="versions")


class BatchJob(Base, TimestampMixin):
    __tablename__ = "batch_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    business_type: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    global_params_json: Mapped[str] = mapped_column(Text, default="{}")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    notification_config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[BatchItem]] = relationship(
        back_populates="batch_job", cascade="all, delete-orphan", order_by="BatchItem.index"
    )


class BatchItem(Base, TimestampMixin):
    __tablename__ = "batch_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_job_id: Mapped[str] = mapped_column(ForeignKey("batch_job.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    generation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    aplus_plan_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    aplus_generation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_job: Mapped[BatchJob] = relationship(back_populates="items")


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_job.id"), nullable=True, index=True)
    aplus_job_id: Mapped[str | None] = mapped_column(ForeignKey("aplus_job.id", ondelete="CASCADE"), nullable=True, index=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("generation_item.id"), nullable=True, index=True)
    node: Mapped[str] = mapped_column(String(80), index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("provider.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_summary: Mapped[str] = mapped_column(Text, default="{}")
    response_summary: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
