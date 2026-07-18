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
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
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
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
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


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_job.id"), nullable=True, index=True)
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
