"""
Ad Exchange main application.
FastAPI service for facilitating real-time bidding between DSPs and SSPs.
"""

from fastapi import FastAPI
from shared.utils import setup_logging, ServiceConfig
from shared.models import HealthCheck

# Service configuration
config = ServiceConfig("ad-exchange")
logger = setup_logging("ad-exchange")

# FastAPI application
app = FastAPI(
    title="Ad Exchange",
    description="Service for facilitating real-time bidding between DSPs and SSPs",
    version="0.1.0"
)


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    return HealthCheck(status="healthy")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)