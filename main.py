from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from db import get_connection
from order_status import OrderStatus, can_transition

app = FastAPI(title="MakanGo")


class Rider(BaseModel):
    id: int
    name: str
    is_available: bool = True


class RiderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class AvailabilityUpdate(BaseModel):
    is_available: bool


@app.get("/")
def home() -> dict[str, str]:
    return {"message": "Welcome to MakanGo"}


@app.get("/riders")
def list_riders() -> list[Rider]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, is_available FROM riders ORDER BY id").fetchall()
    return [Rider(**row) for row in rows]


@app.get("/riders/available")
def list_available_riders() -> list[Rider]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, is_available FROM riders WHERE is_available = true ORDER BY id"
        ).fetchall()
    return [Rider(**row) for row in rows]


@app.get("/riders/{rider_id}")
def get_rider(rider_id: int) -> Rider:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, is_available FROM riders WHERE id = %s", (rider_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Rider not found")
    return Rider(**row)


@app.post("/riders", status_code=201)
def create_rider(new_rider: RiderCreate) -> Rider:
    with get_connection() as conn:
        row = conn.execute(
            "INSERT INTO riders (name) VALUES (%s) RETURNING id, name, is_available",
            (new_rider.name,),
        ).fetchone()
    return Rider(**row)


@app.patch("/riders/{rider_id}/availability")
def update_availability(rider_id: int, update: AvailabilityUpdate) -> Rider:
    with get_connection() as conn:
        row = conn.execute(
            "UPDATE riders SET is_available = %s WHERE id = %s RETURNING id, name, is_available",
            (update.is_available, rider_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Rider not found")
    return Rider(**row)



# ---------- Orders ----------

class OrderCreate(BaseModel):
    """What the client sends to place an order."""
    customer_name: str = Field(min_length=1, max_length=50)
    restaurant: str = Field(min_length=1, max_length=100)


class Order(BaseModel):
    """An order stored in our system."""
    id: int
    customer_name: str
    restaurant: str
    status: OrderStatus


class StatusUpdate(BaseModel):
    """What the client sends to move an order to a new status."""
    status: OrderStatus


@app.post("/orders", status_code=201)
def create_order(new_order: OrderCreate) -> Order:
    """Place a new order. It always starts as PLACED."""
    with get_connection() as conn:
        row = conn.execute(
            "INSERT INTO orders (customer_name, restaurant) VALUES (%s, %s) "
            "RETURNING id, customer_name, restaurant, status",
            (new_order.customer_name, new_order.restaurant),
        ).fetchone()
    return Order(**row)


@app.get("/orders/{order_id}")
def get_order(order_id: int) -> Order:
    """Return one order, or 404 if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, customer_name, restaurant, status FROM orders WHERE id = %s",
            (order_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**row)


@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: int, update: StatusUpdate) -> Order:
    """Move an order to a new status, but only if the rules allow it."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM orders WHERE id = %s FOR UPDATE",
            (order_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Order not found")

        current = OrderStatus(row["status"])
        if not can_transition(current, update.status):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot change order from {current} to {update.status}",
            )

        row = conn.execute(
            "UPDATE orders SET status = %s WHERE id = %s "
            "RETURNING id, customer_name, restaurant, status",
            (update.status.value, order_id),
        ).fetchone()
    return Order(**row)