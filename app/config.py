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
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    JSON_AS_ASCII = False
    IDEMPOTENCY_TTL_DAYS = int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "7"))
    SYNC_PAGE_SIZE = 500


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _db_url(
        os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@/timetable_test?host=/tmp")
    )
    SQLALCHEMY_ENGINE_OPTIONS = {}
