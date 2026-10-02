"""Web Push: RFC 8291 encryption round-trip, VAPID JWT, subscriptions, and alerts sent with notices."""
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.notify import graph, webpush
from tests.helpers import make_user


def _device():
    priv = ec.generate_private_key(ec.SECP256R1())
    auth = webpush.b64u(b"0123456789abcdef")
    return priv, webpush.b64u(webpush._pub_bytes(priv.public_key())), auth


def test_encrypt_decrypt_round_trip():
    priv, p256dh, auth = _device()
    body = webpush.encrypt("مرحباً — حصة إشغال".encode(), p256dh, auth)
    assert webpush.decrypt(body, priv, auth).decode() == "مرحباً — حصة إشغال"


def test_vapid_header_is_a_valid_es256_jwt():
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = webpush.b64u(webpush._pub_bytes(priv.public_key()))
    hdr = webpush.vapid_header("https://fcm.googleapis.com/fcm/send/abc", priv, pub, "mailto:a@b.c")
    t, k = hdr.split(", ")
    jwt = t.removeprefix("vapid t=")
    head, claims, sig = jwt.split(".")
    c = json.loads(webpush.unb64u(claims))
    assert c["aud"] == "https://fcm.googleapis.com" and c["sub"] == "mailto:a@b.c" and k == f"k={pub}"
    raw = webpush.unb64u(sig)
    priv.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                             f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


class FakePush:
    def __init__(self, gone=()):
        self.calls, self.gone = [], set(gone)

    def __call__(self, method, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        if url in self.gone:
            return 410, b""
        return 201, b""


@pytest.fixture
def fake(monkeypatch):
    f = FakePush()
    monkeypatch.setattr(graph, "_http", f)
    return f


def test_subscribe_test_and_gone_devices(admin, fake):
    a = admin
    key = a.ok("get", "/api/push/key")
    assert len(webpush.unb64u(key["public_key"])) == 65 and key["devices"] == 0
    assert a.ok("get", "/api/push/key")["public_key"] == key["public_key"]          # created once
    assert key["public_key"] in json.dumps(a.ok("get", "/api/settings"))           # the public key is public…
    assert "push:vapid" not in a.ok("get", "/api/settings")                       # …the private one is not
    priv, p256dh, auth = _device()
    assert a.post("/api/push/subscribe", json={"endpoint": "http://x", "keys": {}}).status_code == 400
    a.ok("post", "/api/push/subscribe", {"endpoint": "https://push.example/1", "keys": {"p256dh": p256dh, "auth": auth}})
    a.ok("post", "/api/push/subscribe", {"endpoint": "https://push.example/1", "keys": {"p256dh": p256dh, "auth": auth}})
    assert a.ok("get", "/api/push/key")["devices"] == 1
    assert a.ok("post", "/api/push/test", {})["sent"] == 1
    url, body, headers = fake.calls[-1]
    assert headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t=")
    assert json.loads(webpush.decrypt(body, priv, auth))["title"] == "تجربة الإشعارات"
    fake.gone.add("https://push.example/1")
    assert a.ok("post", "/api/push/test", {})["failed"] == 1
    assert a.ok("get", "/api/push/key")["devices"] == 0                             # forgotten


def test_notice_to_a_teacher_alerts_their_phone(school, fake, api):
    a, s = school["api"], school
    uid = make_user("sara@school.test", role="viewer")
    t = a.ok("get", f"/api/teachers/{s['t2']}")
    a.ok("patch", f"/api/teachers/{s['t2']}", {"version": t["version"], "user_id": str(uid)})
    a.ok("post", "/api/duty-assignments", {"term_id": s["term"], "duty_type": "الطابور الصباحي", "teacher_ids": [s["t2"]]})
    a.logout()
    api.login("sara@school.test")
    priv, p256dh, auth = _device()
    api.ok("post", "/api/push/subscribe", {"endpoint": "https://push.example/sara", "keys": {"p256dh": p256dh, "auth": auth}})
    api.logout()
    a.login("admin@school.test")
    r = a.ok("post", "/api/duty-assignments/notify", {"term_id": s["term"], "email": False})
    assert r["push"] == 1 and r["in_app"] == 1
    msg = json.loads(webpush.decrypt(fake.calls[-1][1], priv, auth))
    assert msg["title"].startswith("جدول المناوبة") and "الطابور الصباحي" in msg["body"] and msg["url"] == "/#/duties"
