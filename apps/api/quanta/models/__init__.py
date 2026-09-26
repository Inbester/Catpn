"""SQLAlchemy models. Importing this package registers every table."""

from quanta.models.alert import (
    ALERT_SOURCES,
    DESTINATION_KINDS,
    Alert,
    AlertEvent,
    Channel,
)
from quanta.models.audit import AuditEvent
from quanta.models.bot import (
    BOT_STATES,
    HALT_REASONS,
    Bot,
    BotOrder,
    ExchangeKey,
)
from quanta.models.compute import (
    COMPUTE_FEATURES,
    COMPUTE_SOURCES,
    DEFAULT_ROUTING,
    SERVER_ONLY,
    ComputePreference,
)
from quanta.models.job import JOB_STATES, JobRecord
from quanta.models.market import BackfillState, FundingRate, InstrumentMeta, Kline
from quanta.models.network import (
    ROUTABLE_FEATURES,
    UNROUTABLE,
    FeatureRoute,
    Tunnel,
)
from quanta.models.paper import PaperFill, PaperSession
from quanta.models.setup import PIPELINE_STAGES, SETUP_COLORS, Setup
from quanta.models.strategy import BacktestRun, StrategyRecord
from quanta.models.user import AuthSession, User
from quanta.models.workspace import DOCUMENT_KINDS, WorkspaceDocument, WorkspaceRevision

__all__ = [
    "ALERT_SOURCES",
    "BOT_STATES",
    "COMPUTE_FEATURES",
    "COMPUTE_SOURCES",
    "DEFAULT_ROUTING",
    "DESTINATION_KINDS",
    "DOCUMENT_KINDS",
    "HALT_REASONS",
    "JOB_STATES",
    "PIPELINE_STAGES",
    "ROUTABLE_FEATURES",
    "SERVER_ONLY",
    "SETUP_COLORS",
    "UNROUTABLE",
    "Alert",
    "AlertEvent",
    "AuditEvent",
    "AuthSession",
    "BackfillState",
    "BacktestRun",
    "Bot",
    "BotOrder",
    "Channel",
    "ComputePreference",
    "ExchangeKey",
    "FeatureRoute",
    "FundingRate",
    "InstrumentMeta",
    "JobRecord",
    "Kline",
    "PaperFill",
    "PaperSession",
    "Setup",
    "StrategyRecord",
    "Tunnel",
    "User",
    "WorkspaceDocument",
    "WorkspaceRevision",
]
