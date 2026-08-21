"""SQLAlchemy models.

Every model must be imported here. Alembic autogenerate compares `Base.metadata` against the
database, and a model that is never imported is invisible to it — the symptom is a migration
that silently drops the table.
"""

from turex.db.base import Base
from turex.models.analysis import Analysis, AnalysisCell, CellKind, CellStatus
from turex.models.annotation import Annotation, HighlightColour
from turex.models.catalog import CatalogPaper
from turex.models.conversation import (
    AssistantMode,
    Conversation,
    ConversationMessage,
    MessageCitation,
    MessageRole,
)
from turex.models.job import IngestionJob, IngestionStage, JobKind, JobStatus
from turex.models.library import Collection, CollectionPaper, PaperTag, Tag
from turex.models.paper import (
    EMBEDDING_DIMENSIONS,
    Paper,
    PaperChunk,
    PaperEquation,
    PaperReference,
    PaperSection,
    PaperSource,
    ProcessingStatus,
    ReadingStatus,
)
from turex.models.security import RateLimitCounter
from turex.models.study import (
    CardKind,
    CardReview,
    Flashcard,
    QuestionKind,
    Quiz,
    QuizQuestion,
    ReviewRating,
)
from turex.models.user import User, UserSession
from turex.models.workspace import (
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
    "Analysis",
    "AnalysisCell",
    "Annotation",
    "AssistantMode",
    "Base",
    "CardKind",
    "CardReview",
    "CatalogPaper",
    "CellKind",
    "CellStatus",
    "Collection",
    "CollectionPaper",
    "Conversation",
    "ConversationMessage",
    "Evidence",
    "EvidenceStance",
    "Experiment",
    "ExperimentStatus",
    "Flashcard",
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
    "PaperEquation",
    "PaperReference",
    "PaperSection",
    "PaperSource",
    "PaperTag",
    "ProcessingStatus",
    "Project",
    "ProjectPaper",
    "ProjectStatus",
    "QuestionKind",
    "Quiz",
    "QuizQuestion",
    "RateLimitCounter",
    "ReadingStatus",
    "ReviewRating",
    "Tag",
    "Task",
    "TaskStatus",
    "User",
    "UserSession",
]
