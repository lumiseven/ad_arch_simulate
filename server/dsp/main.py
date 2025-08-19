"""
Demand-Side Platform (DSP) main application.
FastAPI service for real-time bidding on behalf of advertisers.
"""

from fastapi import FastAPI
from shared.utils import setup_logging, ServiceConfig
from shared.models import HealthCheck

# Service configuration
config = ServiceConfig("dsp")
logger = setup_logging("dsp")

# FastAPI application
app = FastAPI(
    title="Demand-Side Platform (DSP)",
    description="Service for real-time bidding on behalf of advertisers",
    version="0.1.0"
)


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    return HealthCheck(status="healthy")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)