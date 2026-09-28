import os

from app import create_app

# On a hosting platform the database must be configured explicitly; without it the app would
# silently fall back to a local development socket and fail with a confusing error.
_HOSTED = any(os.environ.get(k) for k in ("RENDER", "K_SERVICE", "GAE_ENV", "KOYEB_APP_NAME", "DYNO"))
if _HOSTED and not os.environ.get("DATABASE_URL", "").strip():
    raise RuntimeError(
        "DATABASE_URL environment variable is missing. Add it in the hosting dashboard "
        "(Environment) with the Neon connection string: postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
    )

# A remote (production) database with the development secret would let anyone forge sessions.
_db = os.environ.get("DATABASE_URL", "")
if _db and not any(h in _db for h in ("localhost", "127.0.0.1", "host=/tmp")) and not os.environ.get("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY environment variable is required in production")

app = create_app()
