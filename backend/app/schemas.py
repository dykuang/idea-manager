from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


Status = Literal["seed", "exploring", "promising", "parked"]
AgentProvider = Literal["openai", "anthropic", "deepseek", "qwen", "local", "custom"]
ReasoningEffort = Literal["", "none", "minimal", "low", "medium", "high", "xhigh", "max"]


class IdeaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = ""
    raw_text: str | None = None
    status: Status = "seed"
    tags: list[str] = []
    project_id: int | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        return value.strip()


class IdeaUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = ""
    status: Status = "seed"
    tags: list[str] = []
    expected_updated_at: str | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        return value.strip()


class RelationCreate(BaseModel):
    source_id: int
    target_id: int
    relation_type: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=500)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    group_id: int | None = None
    workspace_mode: Literal["library", "linked", "managed"] = "library"
    workspace_path: str = Field(default="", max_length=1000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip()


class ProjectGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip()


class ProjectAssignment(BaseModel):
    project_id: int


class ImportPreviewRequest(BaseModel):
    data: dict[str, Any]


class ImportRequest(ImportPreviewRequest):
    duplicate_strategy: Literal["skip", "copy", "update"] = "skip"
    project_strategy: Literal["merge", "rename"] = "merge"


class AgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def trim_message(cls, value: str) -> str:
        return value.strip()


class AgentRunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    mode: Literal["explore", "elaborate", "critique", "connect", "synthesize"] = "explore"
    conversation: list[AgentMessage] = Field(default_factory=list, max_length=12)
    session_id: int | None = None
    scope_type: Literal["all", "project", "group"] = "all"
    scope_id: int | None = None
    idea_id: int | None = None
    context_idea_ids: list[int] = Field(default_factory=list, max_length=20)
    model: str = Field(default="", max_length=100)
    reasoning_effort: ReasoningEffort = ""
    web_search: bool = False
    attachment_ids: list[int] = Field(default_factory=list, max_length=12)

    @field_validator("prompt")
    @classmethod
    def trim_prompt(cls, value: str) -> str:
        return value.strip()


class DreamRunRequest(BaseModel):
    idea_ids: list[int] = Field(min_length=2, max_length=8)
    prompt: str = Field(default="", max_length=4000)
    project_id: int | None = None
    model: str = Field(default="", max_length=100)

    @field_validator("idea_ids")
    @classmethod
    def distinct_ideas(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("Choose each dream source only once")
        return value

    @field_validator("prompt")
    @classmethod
    def trim_dream_prompt(cls, value: str) -> str:
        return value.strip()


class AgentProposalResolution(BaseModel):
    action: Literal["apply", "dismiss"]


class AgentResultSave(BaseModel):
    action: Literal["update_original", "create_child"]


class CodexCheckpointProposal(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    status: Status = "seed"
    parent_id: int | None = None

    @field_validator("title")
    @classmethod
    def trim_checkpoint_title(cls, value: str) -> str:
        return value.strip()


class CodexCheckpointCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=16000)
    task_title: str = Field(default="", max_length=240)
    project_id: int | None = None
    proposals: list[CodexCheckpointProposal] = Field(default_factory=list, max_length=5)

    @field_validator("summary", "task_title")
    @classmethod
    def trim_checkpoint_value(cls, value: str) -> str:
        return value.strip()


class AttachmentCreate(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    storage_mode: Literal["linked", "managed"] = "linked"


class IdeaAttachmentUpdate(BaseModel):
    asset_role: Literal["attachment", "figure"] | None = None
    caption: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_cover: bool | None = None


class PathChoice(BaseModel):
    initial_path: str = Field(default="", max_length=2000)


class RemoteMachineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=255)
    username: str = Field(default="", max_length=100)
    port: int = Field(default=0, ge=0, le=65535)
    root_path: str = Field(min_length=1, max_length=1000)

    @field_validator("name", "host", "username", "root_path")
    @classmethod
    def trim_remote_value(cls, value: str) -> str:
        value = value.strip()
        if any(char in value for char in "\x00\r\n"):
            raise ValueError("Remote settings cannot contain control characters")
        return value


class ProjectSyncPreview(BaseModel):
    machine_id: int
    project_id: int
    direction: Literal["push", "pull"]
    local_root: str = Field(default="", max_length=2000)


class ProjectSyncExecute(BaseModel):
    preview_id: str = Field(min_length=32, max_length=32)
    selected_paths: list[str] = Field(default_factory=list, max_length=10000)
    delete_paths: list[str] = Field(default_factory=list, max_length=10000)


class TagSettingsUpdate(BaseModel):
    group_name: str = Field(default="", max_length=80)
    is_hidden: bool = False

    @field_validator("group_name")
    @classmethod
    def trim_group(cls, value: str) -> str:
        return value.strip()


class TagRename(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip().lower()


class TagMerge(BaseModel):
    target_name: str = Field(min_length=1, max_length=80)

    @field_validator("target_name")
    @classmethod
    def trim_target(cls, value: str) -> str:
        return value.strip().lower()


class TagBulkUpdate(BaseModel):
    idea_ids: list[int] = Field(min_length=1, max_length=500)
    add_tags: list[str] = Field(default_factory=list, max_length=20)
    remove_tags: list[str] = Field(default_factory=list, max_length=20)


class AgentConnectionCreate(BaseModel):
    provider: AgentProvider = "openai"
    api_key: SecretStr = SecretStr("")
    model: str = Field(default="", max_length=100)
    base_url: str = Field(default="", max_length=500)
    reasoning_effort: ReasoningEffort = ""
    remember_api_key: bool = False

    @field_validator("model", "base_url")
    @classmethod
    def trim_connection_value(cls, value: str) -> str:
        return value.strip()
