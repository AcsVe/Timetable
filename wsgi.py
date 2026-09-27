import os

from app import create_app

# A remote (production) database with the development secret would let anyone forge sessions.
_db = os.environ.get("DATABASE_URL", "")
if _db and not any(h in _db for h in ("localhost", "127.0.0.1", "host=/tmp")) and not os.environ.get("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY environment variable is required in production")

app = create_app()
