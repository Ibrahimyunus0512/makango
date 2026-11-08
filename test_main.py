import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import main  # noqa: E402
from db import get_connection  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_database():
    assert "test" in os.environ["DATABASE_URL"], "Refusing to wipe a non-test database!"
    with get_connection() as conn:
        conn.execute("TRUNCATE orders, riders RESTART IDENTITY")
        conn.execute(
            "INSERT INTO riders (name, is_available) VALUES "
            "('Ali', true), ('Siti', true), ('Raju', false)"
        )


def test_home_returns_welcome_message():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to MakanGo"}


def test_get_rider_returns_ali_for_id_1():
    response = client.get("/riders/1")
    assert response.status_code == 200
    assert response.json()["name"] == "Ali"


def test_get_unknown_rider_returns_404():
    assert client.get("/riders/999").status_code == 404


def test_create_rider_returns_201_with_new_id():
    response = client.post("/riders", json={"name": "Mei Ling"})
    assert response.status_code == 201
    assert response.json() == {"id": 4, "name": "Mei Ling", "is_available": True}


def test_create_rider_rejects_empty_name():
    assert client.post("/riders", json={"name": ""}).status_code == 422


def test_busy_rider_disappears_from_available_list():
    client.patch("/riders/1/availability", json={"is_available": False})
    names = [r["name"] for r in client.get("/riders/available").json()]
    assert "Ali" not in names


def test_update_unknown_rider_returns_404():
    response = client.patch("/riders/999/availability", json={"is_available": False})
    assert response.status_code == 404



def test_create_order_starts_as_placed():
    response = client.post("/orders", json={"customer_name": "Baim", "restaurant": "Nasi Lemak Corner"})
    assert response.status_code == 201
    assert response.json()["status"] == "PLACED"


def test_valid_status_change_is_accepted():
    client.post("/orders", json={"customer_name": "Baim", "restaurant": "Nasi Lemak Corner"})
    response = client.patch("/orders/1/status", json={"status": "ACCEPTED"})
    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"


def test_invalid_status_jump_returns_409():
    client.post("/orders", json={"customer_name": "Baim", "restaurant": "Nasi Lemak Corner"})
    response = client.patch("/orders/1/status", json={"status": "DELIVERED"})
    assert response.status_code == 409


def test_unknown_status_word_returns_422():
    client.post("/orders", json={"customer_name": "Baim", "restaurant": "Nasi Lemak Corner"})
    response = client.patch("/orders/1/status", json={"status": "FLYING"})
    assert response.status_code == 422


def test_status_change_on_unknown_order_returns_404():
    response = client.patch("/orders/999/status", json={"status": "ACCEPTED"})
    assert response.status_code == 404