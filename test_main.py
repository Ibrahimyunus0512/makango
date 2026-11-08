import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_riders():
    """Restore the original riders after each test, so tests don't affect each other."""
    original = [r.model_copy() for r in main.riders]
    yield
    main.riders[:] = original


def test_home_returns_welcome_message():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to MakanGo"}


def test_get_rider_returns_ali_for_id_1():
    response = client.get("/riders/1")
    assert response.status_code == 200
    assert response.json()["name"] == "Ali"


def test_get_unknown_rider_returns_404():
    response = client.get("/riders/999")
    assert response.status_code == 404


def test_create_rider_returns_201_with_new_id():
    response = client.post("/riders", json={"name": "Mei Ling"})
    assert response.status_code == 201
    assert response.json() == {"id": 4, "name": "Mei Ling", "is_available": True}


def test_create_rider_rejects_empty_name():
    response = client.post("/riders", json={"name": ""})
    assert response.status_code == 422


def test_busy_rider_disappears_from_available_list():
    client.patch("/riders/1/availability", json={"is_available": False})
    response = client.get("/riders/available")
    names = [r["name"] for r in response.json()]
    assert "Ali" not in names
    