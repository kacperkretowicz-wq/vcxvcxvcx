import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(settings, "database_path", db_path)
    with TestClient(app) as c:
        yield c


def test_index_empty(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Brak profili" in r.text


def test_create_edit_toggle_delete_profile_flow(client):
    r = client.get("/profiles/new")
    assert r.status_code == 200
    assert "Nowy profil" in r.text

    r = client.post(
        "/profiles",
        data={
            "name": "Grecja wrzesień",
            "country": "Grecja",
            "region": "Kreta",
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "duration_min": "6",
            "duration_max": "8",
            "adults": "2",
            "children": "0",
            "board": "AI",
            "max_price_per_person": "4500",
            "min_hotel_rating": "",
            "min_stars": "",
            "departure_airport": "Warszawa",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    r = client.get("/")
    assert "Grecja wrzesień" in r.text

    profiles = db.list_profiles(db_path=settings.database_path)
    assert len(profiles) == 1
    profile_id = profiles[0]["id"]

    r = client.get(f"/profiles/{profile_id}/edit")
    assert r.status_code == 200
    assert "Grecja wrzesień" in r.text

    r = client.post(
        f"/profiles/{profile_id}",
        data={
            "name": "Grecja wrzesień (zmieniono)",
            "country": "Grecja",
            "region": "",
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "duration_min": "6",
            "duration_max": "8",
            "adults": "2",
            "children": "0",
            "board": "",
            "max_price_per_person": "",
            "min_hotel_rating": "",
            "min_stars": "",
            "departure_airport": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.get("/")
    assert "Grecja wrzesień (zmieniono)" in r.text

    r = client.get(f"/profiles/{profile_id}/offers")
    assert r.status_code == 200
    assert "Brak ofert pasujących" in r.text

    r = client.post(f"/profiles/{profile_id}/toggle-active", follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/")
    assert "wyłączony" in r.text

    client.post(f"/profiles/{profile_id}/toggle-active", follow_redirects=False)
    r = client.get("/")
    assert "aktywny" in r.text

    r = client.post(f"/profiles/{profile_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/")
    assert "Brak profili" in r.text


def test_deals_and_status_pages_render_when_empty(client):
    r = client.get("/deals")
    assert r.status_code == 200
    assert "Brak wykrytych okazji" in r.text

    r = client.get("/status")
    assert r.status_code == 200


def test_edit_unknown_profile_404(client):
    assert client.get("/profiles/999/edit").status_code == 404


def test_offers_unknown_profile_404(client):
    assert client.get("/profiles/999/offers").status_code == 404


def test_offer_history_unknown_404(client):
    assert client.get("/offers/unknown:xyz/history").status_code == 404


def test_run_unknown_profile_404(client):
    assert client.post("/profiles/999/run").status_code == 404
