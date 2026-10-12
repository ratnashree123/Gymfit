"""GymFit API entry point."""
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (loads all models so relationships are configured)
from app.config import get_settings
from app.database import get_db
from app.middleware.error_handlers import register_exception_handlers
from app.routers import auth, invoices, members, payments, plans, reports, staff

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

settings = get_settings()

app = FastAPI(
    title=f"{settings.app_name} API",
    description="Gym Management System REST API",
    version="0.4.0",
)

# Only the configured frontend origins may call this API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth.router, prefix="/api")
app.include_router(staff.router, prefix="/api")
app.include_router(plans.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(invoices.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(reports.router, prefix="/api")


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
