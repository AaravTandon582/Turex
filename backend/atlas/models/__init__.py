"""SQLAlchemy models.

Every model must be imported here. Alembic autogenerate compares `Base.metadata` against the
database, and a model that is never imported is invisible to it — the symptom is a migration
that silently drops the table.
"""

from atlas.db.base import Base
from atlas.models.annotation import Annotation, HighlightColour
from atlas.models.conversation import (
    AssistantMode,
    Conversation,
    ConversationMessage,
    MessageCitation,
    MessageRole,
)
from atlas.models.job import IngestionJob, IngestionStage, JobKind, JobStatus
from atlas.models.library import Collection, CollectionPaper, PaperTag, Tag
from atlas.models.paper import (
    EMBEDDING_DIMENSIONS,
    Paper,
    PaperChunk,
    PaperSection,
    PaperSource,
    ProcessingStatus,
    ReadingStatus,
)
from atlas.models.user import User, UserSession
from atlas.models.workspace import (
    Evidence,
    EvidenceStance,
    Experiment,
    ExperimentStatus,
    Hypothesis,
    HypothesisStatus,
    Note,
    Project,
    ProjectPaper,
    ProjectStatus,
    Task,
    TaskStatus,
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "Annotation",
    "AssistantMode",
    "Base",
    "Collection",
    "CollectionPaper",
    "Conversation",
    "ConversationMessage",
    "Evidence",
    "EvidenceStance",
    "Experiment",
    "ExperimentStatus",
    "HighlightColour",
    "Hypothesis",
    "HypothesisStatus",
    "IngestionJob",
    "IngestionStage",
    "JobKind",
    "JobStatus",
    "MessageCitation",
    "MessageRole",
    "Note",
    "Paper",
    "PaperChunk",
    "PaperSection",
    "PaperSource",
    "PaperTag",
    "ProcessingStatus",
    "Project",
    "ProjectPaper",
    "ProjectStatus",
    "ReadingStatus",
    "Tag",
    "Task",
    "TaskStatus",
    "User",
    "UserSession",
]
