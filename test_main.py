import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import main  # noqa: E402
from db import get_connection  # noqa: E402

client = TestClient(main.app)

# A restaurant in Bangsar South, Kuala Lumpur
PICKUP = {"pickup_latitude": 3.1110, "pickup_longitude": 101.6650}


@pytest.fixture(autouse=True)
def reset_database():
    """Before each test: empty both tables and add the same 3 riders."""
    assert "test" in os.environ["DATABASE_URL"], "Refusing to wipe a non-test database!"
    with get_connection() as conn:
        conn.execute("TRUNCATE orders, riders RESTART IDENTITY")
        conn.execute(
            "INSERT INTO riders (name, is_available, latitude, longitude) VALUES "
            "('Ali', true, 3.1579, 101.7116), "    # KLCC, about 7.3 km away (too far)
            "('Siti', true, 3.1176, 101.6773), "   # Mid Valley, about 1.6 km away
            "('Raju', false, 3.1115, 101.6655)"    # right next door, but BUSY
        )


def place_order(**overrides) -> int:
    """Helper: place an order near the restaurant and return its ID."""
    body = {"customer_name": "Baim", "restaurant": "Nasi Lemak Corner", **PICKUP, **overrides}
    return client.post("/orders", json=body).json()["id"]


def accept(order_id: int) -> None:
    """Helper: move an order to ACCEPTED."""
    client.patch(f"/orders/{order_id}/status", json={"status": "ACCEPTED"})


# ---------- Riders ----------

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
    response = client.post(
        "/riders", json={"name": "Mei Ling", "latitude": 3.14, "longitude": 101.69}
    )
    assert response.status_code == 201
    assert response.json() == {
        "id": 4, "name": "Mei Ling", "is_available": True, "latitude": 3.14, "longitude": 101.69
    }


def test_create_rider_rejects_empty_name():
    response = client.post("/riders", json={"name": "", "latitude": 3.14, "longitude": 101.69})
    assert response.status_code == 422


def test_create_rider_rejects_impossible_latitude():
    response = client.post("/riders", json={"name": "Mei", "latitude": 100, "longitude": 101.69})
    assert response.status_code == 422


def test_busy_rider_disappears_from_available_list():
    client.patch("/riders/1/availability", json={"is_available": False})
    names = [r["name"] for r in client.get("/riders/available").json()]
    assert "Ali" not in names


def test_update_unknown_rider_returns_404():
    response = client.patch("/riders/999/availability", json={"is_available": False})
    assert response.status_code == 404


# ---------- Orders ----------

def test_create_order_starts_as_placed_with_no_rider():
    response = client.post(
        "/orders", json={"customer_name": "Baim", "restaurant": "Nasi Lemak Corner", **PICKUP}
    )
    assert response.status_code == 201
    assert response.json()["status"] == "PLACED"
    assert response.json()["rider_id"] is None


def test_valid_status_change_is_accepted():
    order_id = place_order()
    response = client.patch(f"/orders/{order_id}/status", json={"status": "ACCEPTED"})
    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"


def test_invalid_status_jump_returns_409():
    order_id = place_order()
    response = client.patch(f"/orders/{order_id}/status", json={"status": "DELIVERED"})
    assert response.status_code == 409


def test_unknown_status_word_returns_422():
    order_id = place_order()
    response = client.patch(f"/orders/{order_id}/status", json={"status": "FLYING"})
    assert response.status_code == 422


def test_status_change_on_unknown_order_returns_404():
    response = client.patch("/orders/999/status", json={"status": "ACCEPTED"})
    assert response.status_code == 404


def test_rider_assigned_cannot_be_set_by_hand():
    order_id = place_order()
    accept(order_id)
    response = client.patch(f"/orders/{order_id}/status", json={"status": "RIDER_ASSIGNED"})
    assert response.status_code == 409


# ---------- Rider matching ----------

def test_assign_picks_nearest_available_rider_and_skips_busy_one():
    order_id = place_order()
    accept(order_id)
    response = client.post(f"/orders/{order_id}/assign-rider")
    assert response.status_code == 200
    body = response.json()
    assert body["rider"]["name"] == "Siti"  # Raju is closer but busy; Ali is too far
    assert body["order"]["status"] == "RIDER_ASSIGNED"
    assert body["order"]["rider_id"] == 2
    assert body["distance_km"] == pytest.approx(1.55, abs=0.01)
    assert body["eta_minutes"] == 14


def test_assigned_rider_becomes_unavailable():
    order_id = place_order()
    accept(order_id)
    client.post(f"/orders/{order_id}/assign-rider")
    assert client.get("/riders/2").json()["is_available"] is False


def test_cannot_assign_rider_before_order_is_accepted():
    order_id = place_order()
    response = client.post(f"/orders/{order_id}/assign-rider")
    assert response.status_code == 409


def test_no_rider_nearby_returns_409():
    order_id = place_order(pickup_latitude=5.4141, pickup_longitude=100.3288)  # Penang
    accept(order_id)
    response = client.post(f"/orders/{order_id}/assign-rider")
    assert response.status_code == 409


def test_two_orders_never_get_the_same_rider():
    first = place_order()
    second = place_order()
    accept(first)
    accept(second)
    client.post(f"/orders/{first}/assign-rider")       # takes Siti
    response = client.post(f"/orders/{second}/assign-rider")
    assert response.status_code == 409                 # nobody else free within 5 km


def test_delivering_an_order_frees_the_rider():
    order_id = place_order()
    accept(order_id)
    client.post(f"/orders/{order_id}/assign-rider")
    client.patch(f"/orders/{order_id}/status", json={"status": "PICKED_UP"})
    client.patch(f"/orders/{order_id}/status", json={"status": "DELIVERED"})
    assert client.get("/riders/2").json()["is_available"] is True