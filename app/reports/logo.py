"""School logo bytes for exports: the uploaded logo, or (fallback) the logo URL, cached briefly."""
from __future__ import annotations

import time
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.extensions import db
from app.models import School

_cache: dict[str, tuple[float, bytes | None]] = {}
TTL = 600


def logo_bytes() -> bytes | None:
    school = db.session.scalars(select(School).options(undefer(School.logo_data))).first()
    if school is None:
        return None
    if school.logo_data:
        return bytes(school.logo_data)
    url = school.logo_path or ""
    if not url.startswith(("http://", "https://")):
        return None
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    data = None
    try:
        with urllib.request.urlopen(url, timeout=4) as r:  # noqa: S310 (admin-configured URL)
            if r.status == 200:
                data = r.read(2_000_000)
    except Exception:
        data = None
    _cache[url] = (time.time(), data)
    return data
