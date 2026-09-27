import os


def _db_url(url: str | None) -> str | None:
    """Render/Neon hand out postgres:// URLs; SQLAlchemy + psycopg3 needs postgresql+psycopg://."""
    if not url:
        return url
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _db_url(
        os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres@/timetable?host=/tmp")
    )
    # prepare_threshold=None: safe behind Neon's pooled (PgBouncer) endpoint as well as the direct one.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280, "connect_args": {"prepare_threshold": None}}
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    JSON_AS_ASCII = False
    IDEMPOTENCY_TTL_DAYS = int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7"))
    SYNC_PAGE_SIZE = 500
    # Compression (Flask-Compress). Excel/PDF/PNG are already compressed, so only text types.
    COMPRESS_MIMETYPES = ["text/html", "text/css", "application/javascript", "text/javascript",
                          "application/json", "application/manifest+json"]
    COMPRESS_MIN_SIZE = 600
    # Static files: let browsers revalidate cheaply; the service worker keeps its own copy.
    SEND_FILE_MAX_AGE_DEFAULT = 3600


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _db_url(
        os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@/timetable_test?host=/tmp")
    )
    SQLALCHEMY_ENGINE_OPTIONS = {}
