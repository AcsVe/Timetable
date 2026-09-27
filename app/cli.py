import click
from sqlalchemy import delete, select

from app.extensions import db


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--name", default="مدير النظام")
    def create_admin(email, password, name):
        """Create (or reset the password of) an admin account."""
        from app.models import AppUser

        user = db.session.scalars(select(AppUser).where(AppUser.email == email)).first()
        if user is None:
            user = AppUser(email=email, display_name=name, role="admin")
            db.session.add(user)
        user.role = "admin"
        user.is_active = True
        user.set_password(password)
        db.session.commit()
        click.echo(f"admin ready: {email}")

    @app.cli.command("seed-base")
    def seed_base():
        """Weekdays (Sun–Thu school days) and default settings. Safe to re-run."""
        from app.models import AppSetting, Weekday

        days = [
            (7, "الأحد", "Sunday", 1, True), (1, "الاثنين", "Monday", 2, True),
            (2, "الثلاثاء", "Tuesday", 3, True), (3, "الأربعاء", "Wednesday", 4, True),
            (4, "الخميس", "Thursday", 5, True), (5, "الجمعة", "Friday", 6, False),
            (6, "السبت", "Saturday", 7, False),
        ]
        existing = {w.iso_dow for w in db.session.scalars(select(Weekday))}
        for dow, ar, en, order, school in days:
            if dow not in existing:
                db.session.add(Weekday(iso_dow=dow, name_ar=ar, name_en=en, sort_order=order, is_school_day=school))
        if db.session.get(AppSetting, "offline_edit_enabled") is None:
            db.session.add(AppSetting(key="offline_edit_enabled", value=False))
        db.session.commit()
        click.echo("base data ready")

    @app.cli.command("purge-idempotency")
    def purge_idempotency():
        """Delete expired idempotency records (run daily)."""
        from app.models import IdempotencyKey
        from app.models.base import utcnow

        n = db.session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < utcnow())).rowcount
        db.session.commit()
        click.echo(f"purged {n}")
