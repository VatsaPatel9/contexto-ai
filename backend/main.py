"""FastAPI application entry point for the AI Tutor backend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supertokens_python import get_all_cors_headers
from supertokens_python.framework.fastapi import get_middleware

from backend.auth.supertokens_config import init_supertokens
from backend.config import Settings
from backend.database import init_db

logger = logging.getLogger(__name__)

_PERSONA_PATH = Path(__file__).resolve().parent / "tutor_persona.md"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # --- Startup ---
    logger.info("AI Tutor API starting up")

    # Create pgvector extension and all tables (run in thread to avoid blocking event loop)
    try:
        await asyncio.to_thread(init_db)
        logger.info("Database tables created / verified")
    except Exception as exc:
        logger.error("Database initialization failed: %s", exc)

    # Seed SuperTokens roles and permissions
    try:
        from backend.auth.roles import seed_roles
        await seed_roles()
        logger.info("SuperTokens roles seeded")
    except Exception as exc:
        logger.error("SuperTokens role seeding failed: %s", exc)

    # Load tutor system prompt into app.state for global access
    try:
        app.state.system_prompt = _PERSONA_PATH.read_text(encoding="utf-8")
        logger.info("Tutor system prompt loaded (%d chars)", len(app.state.system_prompt))
    except FileNotFoundError:
        logger.warning("Tutor persona file not found at %s", _PERSONA_PATH)
        app.state.system_prompt = ""

    # Start the nightly cleanup cron (hard-delete expired soft-deleted docs)
    cleanup_task = asyncio.create_task(_run_nightly_cleanup())

    yield

    # --- Shutdown ---
    cleanup_task.cancel()
    logger.info("AI Tutor API shutting down")


async def _run_nightly_cleanup():
    """Background task: run hard-delete cleanup daily at midnight."""
    import datetime as _dt
    from backend.database import SessionLocal
    from backend.jobs.cleanup import hard_delete_expired_documents

    while True:
        # Calculate seconds until next midnight
        now = _dt.datetime.now(_dt.timezone.utc)
        tomorrow = (now + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_seconds = (tomorrow - now).total_seconds()
        logger.info("Cleanup cron: next run in %.0f seconds (midnight UTC)", sleep_seconds)

        await asyncio.sleep(sleep_seconds)

        # Run cleanup
        try:
            db = SessionLocal()
            try:
                count = hard_delete_expired_documents(db)
                logger.info("Cleanup cron: hard-deleted %d expired documents", count)
            finally:
                db.close()
        except Exception as exc:
            logger.error("Cleanup cron failed: %s", exc)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = Settings()

    # Initialise SuperTokens BEFORE creating the app
    init_supertokens(settings)

    app = FastAPI(
        title="AI Tutor API",
        description="Backend API for the AI Tutor chatbot",
        version="1.0.0",
        lifespan=lifespan,
    )

    # SuperTokens middleware (must be added before CORS)
    app.add_middleware(get_middleware())

    # CORS middleware – include SuperTokens headers
    origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"] + get_all_cors_headers(),
    )

    # Import and include routers
    from backend.routers.admin import router as admin_router
    from backend.routers.auth_verify import router as auth_verify_router
    from backend.routers.chat import router as chat_router
    from backend.routers.courses import router as courses_router
    from backend.routers.documents import router as documents_router
    from backend.routers.exams import router as exams_router, student_router as exams_student_router
    from backend.routers.parameters import router as parameters_router
    from backend.routers.profile import router as profile_router

    app.include_router(admin_router)
    app.include_router(auth_verify_router)
    app.include_router(chat_router)
    app.include_router(courses_router)
    app.include_router(documents_router)
    app.include_router(exams_router)
    app.include_router(exams_student_router)
    app.include_router(parameters_router)
    app.include_router(profile_router)

    # Health check
    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
