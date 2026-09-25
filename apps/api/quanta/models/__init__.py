"""SQLAlchemy models. Importing this package registers every table."""

from quanta.models.audit import AuditEvent
from quanta.models.market import BackfillState, FundingRate, InstrumentMeta, Kline
from quanta.models.setup import PIPELINE_STAGES, SETUP_COLORS, Setup
from quanta.models.strategy import BacktestRun, StrategyRecord
from quanta.models.user import AuthSession, User
from quanta.models.workspace import DOCUMENT_KINDS, WorkspaceDocument, WorkspaceRevision

__all__ = [
    "DOCUMENT_KINDS",
    "PIPELINE_STAGES",
    "SETUP_COLORS",
    "AuditEvent",
    "AuthSession",
    "BackfillState",
    "BacktestRun",
    "FundingRate",
    "InstrumentMeta",
    "Kline",
    "Setup",
    "StrategyRecord",
    "User",
    "WorkspaceDocument",
    "WorkspaceRevision",
]
