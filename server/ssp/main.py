"""
Supply-Side Platform (SSP) main application.
FastAPI service for managing ad inventory and publisher revenue.
"""

from fastapi import FastAPI
from shared.utils import setup_logging, ServiceConfig
from shared.models import HealthCheck

# Service configuration
config = ServiceConfig("ssp")
logger = setup_logging("ssp")

# FastAPI application
app = FastAPI(
    title="Supply-Side Platform (SSP)",
    description="Service for managing ad inventory and maximizing publisher revenue",
    version="0.1.0"
)


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    return HealthCheck(status="healthy")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)