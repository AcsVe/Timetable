import uuid

from app.extensions import db
from app.models import AppUser, Stage

APP = None  # set by the session fixture in conftest


def make_user(email, role="admin", stages=(), password="password123", **kw):
    """stages: list of stage id strings."""
    with APP.app_context():
        u = AppUser(email=email, display_name=email.split("@")[0], role=role, **kw)
        u.set_password(password)
        u.stages = [db.session.get(Stage, uuid.UUID(str(s))) for s in stages]
        db.session.add(u)
        db.session.commit()
        return u.id


