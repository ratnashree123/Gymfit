"""GymFit API entry point."""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

settings = get_settings()

app = FastAPI(
    title=f"{settings.app_name} API",
    description="Gym Management System REST API",
    version="0.1.0",
)

# Only the configured frontend origins may call this API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["System"])
def root():
    return {"message": f"Welcome to the {settings.app_name} API", "docs": "/docs"}


@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """Confirms the API is running and MySQL is reachable."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected", "environment": settings.app_env}
    except SQLAlchemyError:
        return {"status": "error", "database": "unreachable"}
