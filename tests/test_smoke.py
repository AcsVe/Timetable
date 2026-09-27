def test_health(api):
    assert api.get("/healthz").get_json() == {"ok": True}
