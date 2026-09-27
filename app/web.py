from flask import Blueprint, render_template
from flask_login import login_required

web_bp = Blueprint("web", __name__)


@web_bp.get("/")
@login_required
def index():
    # The admin UI (RTL, AR/EN, drag & drop, PWA) is the next build phase.
    return render_template("index.html")
