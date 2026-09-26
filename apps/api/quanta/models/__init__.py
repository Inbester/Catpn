"""SQLAlchemy models. Importing this package registers every table."""

from quanta.models.audit import AuditEvent
from quanta.models.compute import (
    COMPUTE_FEATURES,
    COMPUTE_SOURCES,
    DEFAULT_ROUTING,
    SERVER_ONLY,
    ComputePreference,
)
from quanta.models.job import JOB_STATES, JobRecord
from quanta.models.market import BackfillState, FundingRate, InstrumentMeta, Kline
from quanta.models.setup import PIPELINE_STAGES, SETUP_COLORS, Setup
from quanta.models.strategy import BacktestRun, StrategyRecord
from quanta.models.user import AuthSession, User
from quanta.models.workspace import DOCUMENT_KINDS, WorkspaceDocument, WorkspaceRevision

__all__ = [
    "COMPUTE_FEATURES",
    "COMPUTE_SOURCES",
    "DEFAULT_ROUTING",
    "DOCUMENT_KINDS",
    "JOB_STATES",
    "PIPELINE_STAGES",
    "SERVER_ONLY",
    "SETUP_COLORS",
    "AuditEvent",
    "AuthSession",
    "BackfillState",
    "BacktestRun",
    "ComputePreference",
    "FundingRate",
    "InstrumentMeta",
    "JobRecord",
    "Kline",
    "Setup",
    "StrategyRecord",
    "User",
    "WorkspaceDocument",
    "WorkspaceRevision",
]
