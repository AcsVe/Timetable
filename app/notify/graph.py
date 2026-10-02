"""Microsoft Graph e-mail with an app registration (client-credentials flow).

Needed in Microsoft Entra ID (Azure AD) → App registrations:
  * an application with a client secret;
  * API permission  Microsoft Graph → Application → Mail.Send  (with admin consent);
  * a mailbox to send from (e.g. timetable@school.edu.jo) — optionally restrict the app to that mailbox
    with an Exchange "application access policy".

Settings come from environment variables first (MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_MAIL_SENDER),
then from app_setting["mail:graph"] entered by an admin. The secret is never sent back to the browser.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from app.errors import ApiError

KEY = "mail:graph"
ENV = {"tenant_id": "MS_TENANT_ID", "client_id": "MS_CLIENT_ID", "client_secret": "MS_CLIENT_SECRET",
       "sender": "MS_MAIL_SENDER"}
TIMEOUT = 20
_token_cache: dict = {}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GraphError(Exception):
    pass


def _http(method: str, url: str, *, data: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    """One HTTP call (replaced in tests)."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GraphError(f"تعذّر الاتصال بخدمة Microsoft: {getattr(e, 'reason', e)}")


def load_settings() -> dict:
    from app.extensions import db
    from app.models import AppSetting
    row = db.session.get(AppSetting, KEY)
    saved = dict(row.value or {}) if row else {}
    out, source = {}, {}
    for k, env in ENV.items():
        if os.environ.get(env):
            out[k], source[k] = os.environ[env].strip(), "env"
        else:
            out[k], source[k] = (saved.get(k) or "").strip(), "db" if saved.get(k) else None
    out["enabled"] = bool(saved.get("enabled", True))
    out["sender_name"] = saved.get("sender_name") or ""
    out["source"] = source
    return out


def public_settings(s: dict | None = None) -> dict:
    s = s or load_settings()
    return {"tenant_id": s["tenant_id"], "client_id": s["client_id"], "sender": s["sender"],
            "sender_name": s["sender_name"], "enabled": s["enabled"], "has_secret": bool(s["client_secret"]),
            "source": s["source"], "configured": is_configured(s)}


def is_configured(s: dict | None = None) -> bool:
    s = s or load_settings()
    return bool(s["enabled"] and s["tenant_id"] and s["client_id"] and s["client_secret"] and s["sender"])


def save_settings(data: dict) -> dict:
    from app.extensions import db
    from app.models import AppSetting
    row = db.session.get(AppSetting, KEY) or AppSetting(key=KEY, value={})
    cur = dict(row.value or {})
    guid = re.compile(r"^[0-9a-fA-F-]{36}$|^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    for k in ("tenant_id", "client_id", "sender", "sender_name"):
        if k in data:
            v = (data[k] or "").strip()
            if v and k in ("tenant_id",) and not guid.match(v):
                raise ApiError("validation", 400, details={"field": k, "message": "معرّف المستأجر (Tenant ID) غير صالح"})
            if v and k == "client_id" and not re.fullmatch(r"[0-9a-fA-F-]{36}", v):
                raise ApiError("validation", 400, details={"field": k, "message": "معرّف التطبيق (Client ID) غير صالح"})
            if v and k == "sender" and not EMAIL_RE.match(v):
                raise ApiError("validation", 400, details={"field": k, "message": "بريد المرسل غير صالح"})
            cur[k] = v
    if data.get("client_secret"):
        cur["client_secret"] = str(data["client_secret"]).strip()
    if data.get("clear_secret"):
        cur.pop("client_secret", None)
    if "enabled" in data:
        cur["enabled"] = bool(data["enabled"])
    row.value = cur
    db.session.add(row)
    db.session.flush()
    _token_cache.clear()
    return public_settings()


def token(s: dict) -> str:
    key = (s["tenant_id"], s["client_id"])
    hit = _token_cache.get(key)
    if hit and hit[1] > time.time() + 60:
        return hit[0]
    body = urllib.parse.urlencode({"client_id": s["client_id"], "client_secret": s["client_secret"],
                                   "scope": "https://graph.microsoft.com/.default",
                                   "grant_type": "client_credentials"}).encode()
    status, raw = _http("POST", f"https://login.microsoftonline.com/{urllib.parse.quote(s['tenant_id'])}/oauth2/v2.0/token",
                        data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = {}
    if status != 200 or "access_token" not in payload:
        msg = payload.get("error_description") or payload.get("error") or f"HTTP {status}"
        raise GraphError(f"تعذّر الحصول على رمز الدخول من Microsoft: {str(msg).splitlines()[0][:300]}")
    _token_cache[key] = (payload["access_token"], time.time() + int(payload.get("expires_in", 3600)))
    return payload["access_token"]


def send_mail(s: dict, to: str, subject: str, html: str, to_name: str | None = None) -> None:
    tok = token(s)
    msg = {"message": {"subject": subject, "body": {"contentType": "HTML", "content": html},
                       "toRecipients": [{"emailAddress": {"address": to, **({"name": to_name} if to_name else {})}}]},
           "saveToSentItems": False}
    status, raw = _http("POST", f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(s['sender'])}/sendMail",
                        data=json.dumps(msg).encode(), headers={"Authorization": f"Bearer {tok}",
                                                                "Content-Type": "application/json"})
    if status not in (200, 202):
        try:
            err = json.loads(raw or b"{}").get("error", {})
            text = f"{err.get('code', '')}: {err.get('message', '')}".strip(": ")
        except ValueError:
            text = ""
        hint = ""
        if status == 403:
            hint = " — تأكد من منح صلاحية Mail.Send من نوع Application وموافقة المسؤول، ومن أن بريد المرسل مسموح للتطبيق"
        elif status == 404:
            hint = " — بريد المرسل غير موجود في المستأجر"
        raise GraphError(f"رفضت Microsoft إرسال الرسالة (HTTP {status}) {text}{hint}".strip())
