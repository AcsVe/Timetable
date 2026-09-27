from flask import Flask, jsonify
from sqlalchemy import text

from app.config import Config
from app.extensions import db, login_manager, migrate


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.json.ensure_ascii = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from app import models  # noqa: F401  (register mappers)
    from app.api import api_bp
    from app.auth import auth_bp
    from app.cli import register_cli
    from app.web import web_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)
    register_cli(app)

    @app.get("/healthz")
    def healthz():
        db.session.execute(text("SELECT 1"))
        return jsonify(ok=True)

    return app


REQUIRED_EXTENSIONS = ("btree_gist", "citext")


def ensure_extensions() -> None:
    for ext in REQUIRED_EXTENSIONS:
        db.session.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
    db.session.commit()
