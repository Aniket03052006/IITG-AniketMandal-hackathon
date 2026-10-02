"""The API serves the built UI (single-process deployment) without shadowing /api."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventshock.api.main import create_app
from eventshock.config import Settings


@pytest.fixture()
def spa_client(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>EventShock</title>")
    (tmp_path / "logo.svg").write_text("<svg/>")
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("top secret")
    return TestClient(create_app(Settings(web_dist_dir=tmp_path)))


def test_root_and_client_routes_serve_index(spa_client):
    assert "<title>EventShock</title>" in spa_client.get("/").text
    assert "<title>EventShock</title>" in spa_client.get("/events/sig_0001").text


def test_static_assets_are_served(spa_client):
    assert spa_client.get("/logo.svg").text == "<svg/>"
    assert spa_client.head("/logo.svg").status_code == 200


def test_unknown_api_paths_are_404_not_the_spa(spa_client):
    r = spa_client.get("/api/nope")
    assert r.status_code == 404 and "<title>" not in r.text


def test_api_still_works_next_to_the_spa(spa_client):
    assert spa_client.get("/api/health").json() == {"status": "ok"}
    assert spa_client.get("/api/docs").status_code == 200


def test_path_traversal_is_blocked(spa_client):
    r = spa_client.get("/..%2fsecret.txt")
    assert "top secret" not in r.text


def test_without_a_build_the_api_runs_alone(tmp_path):
    client = TestClient(create_app(Settings(web_dist_dir=tmp_path / "missing")))
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404
