from typing import Annotated

import psycopg
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from db import get_connection
from geo import estimate_eta_minutes, find_nearest_rider
from order_status import OrderStatus, can_transition

app = FastAPI(title="MakanGo")

MAX_PICKUP_DISTANCE_KM = 5.0

# Column lists we reuse in many queries.
# Safe to put inside SQL: fixed text written by us, never user input.
RIDER_COLUMNS = "id, name, is_available, latitude, longitude"
ORDER_COLUMNS = "id, customer_name, restaurant, status, pickup_latitude, pickup_longitude, rider_id"


# ---------- Data shapes (models) ----------

class Rider(BaseModel):
    """A rider stored in our system."""
    id: int
    name: str
    is_available: bool
    latitude: float
    longitude: float


class RiderCreate(BaseModel):
    """What the client must send to add a new rider."""
    name: str = Field(min_length=1, max_length=50)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AvailabilityUpdate(BaseModel):
    """What the client sends to change a rider's availability."""
    is_available: bool


class Order(BaseModel):
    """An order stored in our system."""
    id: int
    customer_name: str
    restaurant: str
    status: OrderStatus
    pickup_latitude: float
    pickup_longitude: float
    rider_id: int | None


class OrderCreate(BaseModel):
    """What the client sends to place an order."""
    customer_name: str = Field(min_length=1, max_length=50)
    restaurant: str = Field(min_length=1, max_length=100)
    pickup_latitude: float = Field(ge=-90, le=90)
    pickup_longitude: float = Field(ge=-180, le=180)


class StatusUpdate(BaseModel):
    """What the client sends to move an order to a new status."""
    status: OrderStatus


class Assignment(BaseModel):
    """The result of matching an order with a rider."""
    order: Order
    rider: Rider
    distance_km: float
    eta_minutes: int


# ---------- Home ----------

@app.get("/")
def home() -> dict[str, str]:
    """Welcome message."""
    return {"message": "Welcome to MakanGo"}


# ---------- Riders ----------

@app.get("/riders")
def list_riders() -> list[Rider]:
    """Return all riders."""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT {RIDER_COLUMNS} FROM riders ORDER BY id").fetchall()
    return [Rider(**row) for row in rows]


@app.get("/riders/available")
def list_available_riders() -> list[Rider]:
    """Return only riders who are free to deliver."""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {RIDER_COLUMNS} FROM riders WHERE is_available = true ORDER BY id"
        ).fetchall()
    return [Rider(**row) for row in rows]


@app.get("/riders/{rider_id}")
def get_rider(rider_id: int) -> Rider:
    """Return one rider by ID, or 404 if not found."""
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {RIDER_COLUMNS} FROM riders WHERE id = %s", (rider_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Rider not found")
    return Rider(**row)


@app.post("/riders", status_code=201)
def create_rider(new_rider: RiderCreate) -> Rider:
    """Add a new rider at a starting location."""
    with get_connection() as conn:
        row = conn.execute(
            f"INSERT INTO riders (name, latitude, longitude) VALUES (%s, %s, %s) "
            f"RETURNING {RIDER_COLUMNS}",
            (new_rider.name, new_rider.latitude, new_rider.longitude),
        ).fetchone()
    return Rider(**row)


@app.patch("/riders/{rider_id}/availability")
def update_availability(rider_id: int, update: AvailabilityUpdate) -> Rider:
    """Mark a rider as available or busy, or 404 if not found."""
    with get_connection() as conn:
        row = conn.execute(
            f"UPDATE riders SET is_available = %s WHERE id = %s RETURNING {RIDER_COLUMNS}",
            (update.is_available, rider_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Rider not found")
    return Rider(**row)


# ---------- Orders ----------

@app.post("/orders", status_code=201)
def create_order(new_order: OrderCreate) -> Order:
    """Place a new order. It always starts as PLACED."""
    with get_connection() as conn:
        row = conn.execute(
            "INSERT INTO orders (customer_name, restaurant, pickup_latitude, pickup_longitude) "
            f"VALUES (%s, %s, %s, %s) RETURNING {ORDER_COLUMNS}",
            (
                new_order.customer_name,
                new_order.restaurant,
                new_order.pickup_latitude,
                new_order.pickup_longitude,
            ),
        ).fetchone()
    return Order(**row)


@app.get("/orders/{order_id}")
def get_order(order_id: int) -> Order:
    """Return one order, or 404 if not found."""
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {ORDER_COLUMNS} FROM orders WHERE id = %s", (order_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**row)


@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: int, update: StatusUpdate) -> Order:
    """Move an order to a new status, but only if the rules allow it."""
    if update.status == OrderStatus.RIDER_ASSIGNED:
        raise HTTPException(
            status_code=409,
            detail=f"Use POST /orders/{order_id}/assign-rider to assign a rider",
        )

    with get_connection() as conn:
        row = conn.execute(
            "SELECT status, rider_id FROM orders WHERE id = %s FOR UPDATE", (order_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Order not found")

        current = OrderStatus(row["status"])
        if not can_transition(current, update.status):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot change order from {current} to {update.status}",
            )

        # Delivery finished: the rider is free for the next order
        if update.status == OrderStatus.DELIVERED and row["rider_id"] is not None:
            conn.execute(
                "UPDATE riders SET is_available = true WHERE id = %s", (row["rider_id"],)
            )

        row = conn.execute(
            f"UPDATE orders SET status = %s WHERE id = %s RETURNING {ORDER_COLUMNS}",
            (update.status.value, order_id),
        ).fetchone()
    return Order(**row)


@app.post("/orders/{order_id}/assign-rider")
def assign_rider(order_id: int) -> Assignment:
    """Give an ACCEPTED order to the nearest available rider within 5 km."""
    with get_connection() as conn:
        # 1. Lock the order so nobody else changes it while we work
        order_row = conn.execute(
            "SELECT status, pickup_latitude, pickup_longitude FROM orders "
            "WHERE id = %s FOR UPDATE",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if not can_transition(OrderStatus(order_row["status"]), OrderStatus.RIDER_ASSIGNED):
            raise HTTPException(
                status_code=409, detail="Order must be ACCEPTED before assigning a rider"
            )

        # 2. Lock all available riders so two orders can't grab the same one
        available = conn.execute(
            "SELECT id, latitude, longitude FROM riders "
            "WHERE is_available = true ORDER BY id FOR UPDATE"
        ).fetchall()

        # 3. Pick the closest one
        match = find_nearest_rider(
            available,
            order_row["pickup_latitude"],
            order_row["pickup_longitude"],
            MAX_PICKUP_DISTANCE_KM,
        )
        if match is None:
            raise HTTPException(
                status_code=409,
                detail=f"No available rider within {MAX_PICKUP_DISTANCE_KM:g} km",
            )
        chosen, distance_km = match

        # 4. Save: rider becomes busy, order gets the rider
        rider_row = conn.execute(
            f"UPDATE riders SET is_available = false WHERE id = %s RETURNING {RIDER_COLUMNS}",
            (chosen["id"],),
        ).fetchone()
        order_row = conn.execute(
            f"UPDATE orders SET status = %s, rider_id = %s WHERE id = %s RETURNING {ORDER_COLUMNS}",
            (OrderStatus.RIDER_ASSIGNED.value, chosen["id"], order_id),
        ).fetchone()

    return Assignment(
        order=Order(**order_row),
        rider=Rider(**rider_row),
        distance_km=round(distance_km, 2),
        eta_minutes=estimate_eta_minutes(distance_km),
    )



# ---------- Payments ----------
# The purpose is avoid any error
class PaymentCreate(BaseModel):
    amount_cents: int = Field(gt=0, le=1_000_000)


class Payment(BaseModel):
    """A payment stored in our system."""
    id: int
    order_id: int
    amount_cents: int
    idempotency_key: str


PAYMENT_COLUMNS = "id, order_id, amount_cents, idempotency_key"


@app.post("/orders/{order_id}/payments", status_code=201)
def pay_for_order(
    order_id: int,
    payment: PaymentCreate,
    response: Response,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
) -> Payment:
    """Charge an order exactly once, even if the same request arrives many times."""
    with get_connection() as conn:
        # 1. Lock the order. Identical requests now wait in line, one at a time.
        order_row = conn.execute(
            "SELECT status FROM orders WHERE id = %s FOR UPDATE", (order_id,)
        ).fetchone()
        if order_row is None:
            raise HTTPException(status_code=404, detail="Order not found")

        # 2. Seen this key before? Then it's a retry: return the SAME payment, charge nothing.
        existing = conn.execute(
            f"SELECT {PAYMENT_COLUMNS} FROM payments WHERE idempotency_key = %s",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            if existing["order_id"] != order_id or existing["amount_cents"] != payment.amount_cents:
                raise HTTPException(
                    status_code=409,
                    detail="This Idempotency-Key was already used for a different payment",
                )
            response.status_code = 200  # replay: nothing new was created
            return Payment(**existing)

        # 3. Business rules
        if OrderStatus(order_row["status"]) == OrderStatus.CANCELLED:
            raise HTTPException(status_code=409, detail="Cannot pay for a cancelled order")
        already_paid = conn.execute(
            "SELECT 1 FROM payments WHERE order_id = %s", (order_id,)
        ).fetchone()
        if already_paid is not None:
            raise HTTPException(status_code=409, detail="Order is already paid")

        # 4. Charge it (the UNIQUE rules in the database are the last safety net)
        try:
            row = conn.execute(
                "INSERT INTO payments (order_id, amount_cents, idempotency_key) "
                f"VALUES (%s, %s, %s) RETURNING {PAYMENT_COLUMNS}",
                (order_id, payment.amount_cents, idempotency_key),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(
                status_code=409,
                detail="This Idempotency-Key was already used for a different payment",
            ) from None
    return Payment(**row)