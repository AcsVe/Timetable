try:
    from flask_compress import Compress
except ImportError:            # the phone (Termux) runs without it: brotli/zstandard need compiling there
    class Compress:            # noqa: D401 - same interface, does nothing
        def init_app(self, app):
            return None
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Deterministic constraint names so Alembic migrations are stable.
naming = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=naming))
migrate = Migrate()
login_manager = LoginManager()
compress = Compress()


# pg8000 (the phone standby's driver) reports only unique violations as IntegrityError; exclusion
# (23P01), foreign-key (23503) and check violations come as ProgrammingError. Every class-23 error is an
# integrity error, as with psycopg, so the same handlers turn them into clear messages.
from sqlalchemy import event as _event, exc as _sa_exc  # noqa: E402
from sqlalchemy.engine import Engine as _Engine  # noqa: E402


@_event.listens_for(_Engine, "handle_error")
def _class23_is_integrity(ctx):
    orig = ctx.original_exception
    if isinstance(ctx.sqlalchemy_exception, _sa_exc.IntegrityError) or not getattr(orig, "args", None):
        return None
    info = orig.args[0]
    if isinstance(info, dict) and str(info.get("C", "")).startswith("23"):
        return _sa_exc.IntegrityError(ctx.statement, ctx.parameters, orig)
    return None
