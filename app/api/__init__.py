from flask import Blueprint

from app.errors import ApiError

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(ApiError)
def _api_error(e: ApiError):
    return e.response()


@api_bp.errorhandler(404)
def _nf(e):
    return ApiError("not_found", 404).response()


from app.api import scheduling, reports, sync, importing, loads, school_ops, cover, crud  # noqa: E402,F401  (specific routes before the generic CRUD)
