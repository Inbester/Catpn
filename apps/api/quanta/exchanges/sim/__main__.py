"""Run the Bitunix simulator: ``python -m quanta.exchanges.sim``."""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "quanta.exchanges.sim.server:sim_app",
        host=os.environ.get("SIM_HOST", "127.0.0.1"),
        port=int(os.environ.get("SIM_PORT", "8100")),
        log_level="warning",
    )
