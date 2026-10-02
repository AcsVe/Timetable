"""Web Push (notifications on phones and computers, also when the app is closed).

Implemented directly on `cryptography` — VAPID (RFC 8292, ES256 JWT) and message encryption with
aes128gcm (RFC 8291 / RFC 8188) — so no package with native build steps is needed on the server.

Keys: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY (base64url) from the environment, otherwise generated once
and kept in app_setting ("vapid_public_key" is public, "push:vapid" holds the private key).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.notify import graph   # shares the HTTP helper (replaced in tests)

TTL = 24 * 3600


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pub_bytes(pub: ec.EllipticCurvePublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _priv_from_raw(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


# ---------------------------------------------------------------------------
# VAPID keys
# ---------------------------------------------------------------------------
def vapid_keys() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """(private key, public key as base64url) — created and stored on first use."""
    env_priv, env_pub = os.environ.get("VAPID_PRIVATE_KEY"), os.environ.get("VAPID_PUBLIC_KEY")
    if env_priv:
        priv = _priv_from_raw(unb64u(env_priv.strip()))
        return priv, env_pub.strip() if env_pub else b64u(_pub_bytes(priv.public_key()))
    from app.extensions import db
    from app.models import AppSetting
    row = db.session.get(AppSetting, "push:vapid")
    if row and (row.value or {}).get("private"):
        priv = _priv_from_raw(unb64u(row.value["private"]))
        return priv, b64u(_pub_bytes(priv.public_key()))
    priv = ec.generate_private_key(ec.SECP256R1())
    raw = priv.private_numbers().private_value.to_bytes(32, "big")
    pub = b64u(_pub_bytes(priv.public_key()))
    db.session.add(AppSetting(key="push:vapid", value={"private": b64u(raw)}))
    pub_row = db.session.get(AppSetting, "vapid_public_key") or AppSetting(key="vapid_public_key")
    pub_row.value = pub
    db.session.add(pub_row)
    db.session.flush()
    return priv, pub


def vapid_header(endpoint: str, priv: ec.EllipticCurvePrivateKey, pub: str, subject: str) -> str:
    u = urllib.parse.urlsplit(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": subject}
    signing_input = f"{b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())}." \
                    f"{b64u(json.dumps(claims, separators=(',', ':')).encode())}"
    r, s = decode_dss_signature(priv.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = f"{signing_input}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={pub}"


# ---------------------------------------------------------------------------
# RFC 8291 encryption
# ---------------------------------------------------------------------------
def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(payload: bytes, p256dh: str, auth: str, *, _as_key=None, _salt=None) -> bytes:
    ua_pub_raw = unb64u(p256dh)
    auth_secret = unb64u(auth)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_raw)
    as_priv = _as_key or ec.generate_private_key(ec.SECP256R1())
    as_pub_raw = _pub_bytes(as_priv.public_key())
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_pub_raw + as_pub_raw + b"\x01")[:32]
    salt = _salt or os.urandom(16)
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_pub_raw)) + as_pub_raw + record


def decrypt(body: bytes, ua_priv: ec.EllipticCurvePrivateKey, auth: str) -> bytes:
    """Receiver side (used by the tests to prove the encryption)."""
    salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_pub_raw = body[21:21 + idlen]
    record = body[21 + idlen:]
    ua_pub_raw = _pub_bytes(ua_priv.public_key())
    shared = ua_priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub_raw))
    prk_key = _hmac(unb64u(auth), shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_pub_raw + as_pub_raw + b"\x01")[:32]
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    plain = AESGCM(cek).decrypt(nonce, record, None)
    assert rs == 4096 and plain.endswith(b"\x02")
    return plain[:-1]


# ---------------------------------------------------------------------------
def send(sub, data: dict, subject: str) -> int:
    """Send one notification; returns the push service's HTTP status (201 = accepted, 404/410 = gone)."""
    priv, pub = vapid_keys()
    body = encrypt(json.dumps(data, ensure_ascii=False).encode()[:3800], sub.p256dh, sub.auth)
    status, _raw = graph._http("POST", sub.endpoint, data=body, headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(TTL),
        "Urgency": "normal", "Authorization": vapid_header(sub.endpoint, priv, pub, subject)})
    return status


def push_to_user(user_id, title: str, body: str, url: str | None) -> dict:
    """Send to every device the user has enabled; forget devices the push service says are gone."""
    from sqlalchemy import select
    from app.extensions import db
    from app.models import AppUser, PushSubscription
    from app.models.base import utcnow
    user = db.session.get(AppUser, user_id)
    subject = f"mailto:{os.environ.get('VAPID_SUBJECT_EMAIL') or (user.email if user else 'admin@localhost')}"
    sent = failed = 0
    for sub in db.session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)):
        try:
            status = send(sub, {"title": title, "body": body[:240], "url": url or "/"}, subject)
        except graph.GraphError:
            failed += 1
            continue
        if status in (200, 201, 202):
            sub.last_success_at = utcnow()
            sent += 1
        elif status in (404, 410):
            db.session.delete(sub)
            failed += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed}
