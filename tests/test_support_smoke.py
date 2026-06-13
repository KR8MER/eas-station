"""Smoke test for the dedicated /support page."""


def test_support_page_renders(app_client):
    resp = app_client.get("/support")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Hero copy unique to the rendered template (not the error fallback).
    assert "Support EAS Station" in body
    assert "Where Your Support Goes" in body
    assert "ko-fi.com/easstation" in body
