from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .settings import get_settings


CaptureStatus = Literal["observed", "unknown", "unavailable", "metadata_only"]


class ObservedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=4096)
    capture_status: CaptureStatus
    reason: str | None = Field(default=None, max_length=512)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if len(value) > get_settings().max_url_chars:
            raise ValueError("URL exceeds configured size limit")
        if not value.startswith(("https://", "http://")):
            raise ValueError("URL must use HTTP or HTTPS")
        return value

    @model_validator(mode="after")
    def explain_missing_context(self) -> "ObservedField":
        if self.capture_status in {"unknown", "unavailable"} and not self.reason:
            raise ValueError("reason is required when context is unknown or unavailable")
        return self


class PromptField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    capture_status: Literal["observed", "unavailable"] = "observed"
    reason: str | None = Field(default=None, max_length=512)

    @field_validator("text")
    @classmethod
    def enforce_prompt_limit(cls, value: str) -> str:
        if len(value) > get_settings().max_prompt_chars:
            raise ValueError("prompt exceeds configured size limit")
        return value


class AttachmentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=512)
    mime_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0, le=9007199254740991, strict=True)
    capture_status: Literal["metadata_only", "presence_only", "unavailable"]
    source: Literal["visible_card", "selection_event"] | None = None
    association_status: Literal["ambiguous"] | None = None

    @model_validator(mode="after")
    def validate_metadata(self) -> "AttachmentMetadata":
        if self.capture_status == "presence_only" and any(value is not None for value in (self.name, self.mime_type, self.size_bytes)):
            raise ValueError("presence_only cannot contain metadata")
        return self


class FileObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_status: Literal["observed", "not_observed", "unavailable"] = "unavailable"
    items: list[AttachmentMetadata] = Field(default_factory=list)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_observation(self) -> "FileObservation":
        if len(self.items) > get_settings().max_attachments:
            raise ValueError("too many file metadata entries")
        if self.capture_status != "observed" and (self.items or self.truncated):
            raise ValueError("file evidence requires observed status")
        return self


class InteractionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"]
    client_event_id: UUID
    platform: Literal["chatgpt_web", "claude_web"]
    usage_context: Literal["work", "chat", "unknown"] = "unknown"
    usage_context_source: Literal["interface_marker", "unknown"] = "unknown"
    device_installation_id: UUID
    account_label: str | None = Field(default=None, max_length=320)
    project: ObservedField
    conversation: ObservedField
    prompt: PromptField
    attachments: list[AttachmentMetadata] = Field(default_factory=list)
    attachments_capture_status: Literal["observed", "not_observed", "unavailable"] = "unavailable"
    attachments_truncated: bool = False
    adapter_version: str = Field(min_length=1, max_length=64)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_usage_context_source(self) -> "InteractionCreate":
        if self.usage_context == "unknown" and self.usage_context_source != "unknown":
            raise ValueError("unknown usage context requires unknown source")
        if self.usage_context != "unknown" and self.usage_context_source != "interface_marker":
            raise ValueError("observed usage context requires interface marker source")
        return self

    @model_validator(mode="after")
    def validate_attachment_observation(self) -> "InteractionCreate":
        if self.attachments_capture_status == "not_observed" and self.attachments:
            raise ValueError("attachment evidence requires observed status")
        if self.attachments_truncated and self.attachments_capture_status != "observed":
            raise ValueError("truncation requires observed status")
        return self

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("attachments")
    @classmethod
    def enforce_attachment_limit(cls, value: list[AttachmentMetadata]) -> list[AttachmentMetadata]:
        if len(value) > get_settings().max_attachments:
            raise ValueError("too many attachment metadata entries")
        return value


class ResponseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_event_id: UUID
    text: str
    generated_materials: FileObservation = Field(default_factory=FileObservation)
    capture_status: Literal["complete", "incomplete"]
    observed_at: datetime
    adapter_version: str | None = Field(default=None, max_length=64)

    @field_validator("text")
    @classmethod
    def enforce_response_limit(cls, value: str) -> str:
        if len(value) > get_settings().max_response_chars:
            raise ValueError("response exceeds configured size limit")
        return value

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)


class StreamCaptureCreate(BaseModel):
    """Metadata-only stream record; content fields are rejected by extra=forbid."""
    model_config = ConfigDict(extra="forbid")

    capture_id: UUID
    device_installation_id: UUID
    platform: Literal["chatgpt_web"]
    path: Literal["/backend-api/f/conversation"]
    request_id: int = Field(ge=0, le=9007199254740991, strict=True)
    status_code: int = Field(ge=100, le=599, strict=True)
    content_type: Literal["text/event-stream"]
    capture_status: Literal["complete", "incomplete"]
    response_chars: int = Field(ge=1, le=100000, strict=True)
    bytes: int = Field(ge=0, le=4000000, strict=True)
    chunks: int = Field(ge=0, le=4000000, strict=True)
    frames: int = Field(ge=0, le=4000000, strict=True)
    done_markers: int = Field(ge=0, le=1000, strict=True)
    protocol_done: bool
    reader_done: bool
    reader_aborted_after_done: bool
    truncated: bool
    stream_elapsed_ms: int = Field(ge=0, le=180000, strict=True)
    event_types: list[str] = Field(max_length=32)
    event_shapes: list[str] = Field(max_length=32)
    event_sequence: list[str] = Field(max_length=32)
    observed_at: datetime
    adapter_version: Literal["0.3.0"]

    @field_validator("event_types", "event_shapes", "event_sequence")
    @classmethod
    def validate_safe_labels(cls, values: list[str]) -> list[str]:
        import re
        if any(len(value) > 200 or not re.fullmatch(r"[a-zA-Z0-9_.:=-]{1,200}", value) for value in values):
            raise ValueError("invalid event labels")
        return values

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_completion(self) -> "StreamCaptureCreate":
        if self.capture_status == "complete" and (
            not self.protocol_done or not (self.reader_done or self.reader_aborted_after_done) or self.truncated
        ):
            raise ValueError("complete capture has inconsistent terminal state")
        if self.reader_aborted_after_done and (self.reader_done or not self.protocol_done or self.truncated):
            raise ValueError("invalid reader abort state")
        return self


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    source: Literal["active_route_at_request"]


class ArtifactMetadataCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    device_installation_id: UUID
    platform: Literal["chatgpt_web"]
    source: Literal["download_headers"]
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=127)
    size_bytes: int | None = Field(default=None, ge=0, le=9007199254740991, strict=True)
    conversation_context: ConversationContext | None = None
    size_source: Literal["content_length", "unavailable"] | None = None
    observed_at: datetime

    @model_validator(mode="after")
    def validate_metadata_provenance(self) -> "ArtifactMetadataCreate":
        if self.size_source == "content_length" and self.size_bytes is None:
            raise ValueError("content_length requires size_bytes")
        if self.size_source == "unavailable" and self.size_bytes is not None:
            raise ValueError("unavailable size cannot include size_bytes")
        return self

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str | None) -> str | None:
        if value is not None and (not value or value in {".", ".."} or any(char in value for char in "\\/\x00") or
                                  any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("invalid file name")
        return value

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str | None) -> str | None:
        if value is not None:
            import re
            if not re.fullmatch(r"[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+", value):
                raise ValueError("invalid MIME type")
            return value.lower()
        return value

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_some_metadata(self) -> "ArtifactMetadataCreate":
        if self.file_name is None and self.mime_type is None and self.size_bytes is None:
            raise ValueError("at least one file metadata field is required")
        return self


class EventRecord(BaseModel):
    event_type: str
    result: str
    error_code: str | None
    occurred_at: datetime


class InteractionAccepted(BaseModel):
    interaction_id: UUID
    status: str
    received_at: datetime
    duplicate: bool = False


class ResponseAccepted(BaseModel):
    interaction_id: UUID
    status: str
    received_at: datetime
    duplicate: bool = False


class StreamCaptureAccepted(BaseModel):
    capture_id: UUID
    status: Literal["stored"]
    received_at: datetime
    attributed_person: str
    duplicate: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok"]
    schema_version: str


class InteractionDetail(BaseModel):
    interaction_id: UUID
    client_event_id: UUID
    device_installation_id: UUID
    platform: str
    account_label: str | None
    attributed_person: str | None = None
    employee_id: str | None = None
    department_code: str | None = None
    usage_context: str = "unknown"
    usage_context_source: str = "unknown"
    project_id: str | None = None
    machine_key_fingerprint: str | None = None
    project: dict[str, Any]
    conversation: dict[str, Any]
    prompt: dict[str, Any]
    attachments: list[dict[str, Any]]
    attachments_capture_status: str
    attachments_truncated: bool
    adapter_version: str
    status: str
    observed_at: datetime
    received_at: datetime
    source_ip: str | None
    responses: list[dict[str, Any]]
    events: list[EventRecord]
