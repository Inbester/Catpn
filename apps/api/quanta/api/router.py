"""Aggregate router for the versioned API."""

from fastapi import APIRouter

from quanta.api.routes import auth, health, market, users, workspace

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(workspace.router)
api_router.include_router(market.router)
