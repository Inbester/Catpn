"""Aggregate router for the versioned API."""

from fastapi import APIRouter

from quanta.api.routes import (
    auth,
    forward,
    health,
    market,
    research,
    strategies,
    users,
    workspace,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(workspace.router)
api_router.include_router(market.router)
api_router.include_router(strategies.router)
api_router.include_router(strategies.backtests_router)
api_router.include_router(forward.router)
api_router.include_router(forward.setups_router)
api_router.include_router(research.router)
api_router.include_router(research.jobs_router)
