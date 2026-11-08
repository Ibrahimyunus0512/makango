from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="MakanGo")


# ---------- Data shapes (models) ----------

class Rider(BaseModel):
    """A rider stored in our system."""
    id: int
    name: str
    is_available: bool = True


class RiderCreate(BaseModel):
    """What the client must send to add a new rider."""
    name: str = Field(min_length=1, max_length=50)


class AvailabilityUpdate(BaseModel):
    """What the client sends to change a rider's availability."""
    is_available: bool


# ---------- Pretend database ----------

riders: list[Rider] = [
    Rider(id=1, name="Ali"),
    Rider(id=2, name="Siti"),
    Rider(id=3, name="Raju", is_available=False),
]


def find_rider(rider_id: int) -> Rider:
    """Return the rider with this ID, or raise a 404 error."""
    for r in riders:
        if r.id == rider_id:
            return r
    raise HTTPException(status_code=404, detail="Rider not found")


# ---------- Routes ----------

@app.get("/")
def home() -> dict[str, str]:
    """Welcome message."""
    return {"message": "Welcome to MakanGo"}


@app.get("/riders")
def list_riders() -> list[Rider]:
    """Return all riders."""
    return riders


@app.get("/riders/available")
def list_available_riders() -> list[Rider]:
    """Return only riders who are free to deliver."""
    return [r for r in riders if r.is_available]


@app.get("/riders/{rider_id}")
def get_rider(rider_id: int) -> Rider:
    """Return one rider by ID."""
    return find_rider(rider_id)


@app.post("/riders", status_code=201)
def create_rider(new_rider: RiderCreate) -> Rider:
    """Add a new rider and give them the next ID."""
    next_id = max((r.id for r in riders), default=0) + 1
    rider = Rider(id=next_id, name=new_rider.name)
    riders.append(rider)
    return rider


@app.patch("/riders/{rider_id}/availability")
def update_availability(rider_id: int, update: AvailabilityUpdate) -> Rider:
    """Mark a rider as available or busy."""
    rider = find_rider(rider_id)
    rider.is_available = update.is_available
    return rider