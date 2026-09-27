from flask import Flask, jsonify
from sqlalchemy import text

from app.config import Config
from app.extensions import compress, db, login_manager, migrate


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.json.ensure_ascii = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    compress.init_app(app)  # gzip/brotli: JSON and JS shrink ~70–85%, which matters on bandwidth-capped hosts

    @app.after_request
    def _allow_static_compression(resp):
        # send_file() streams files ("direct passthrough"), which Flask-Compress skips; our static
        # files are small text, so read them into memory and let them be compressed too.
        # (Registered after Compress, so it runs before Compress's own after_request hook.)
        if resp.direct_passthrough and resp.mimetype in app.config["COMPRESS_MIMETYPES"] and resp.status_code == 200:
            resp.direct_passthrough = False
            resp.set_data(resp.get_data())  # buffered (not streamed) → compressed with gzip/brotli
        return resp

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
