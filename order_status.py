from enum import StrEnum


class OrderStatus(StrEnum):
    """Every step an order can be in."""
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    RIDER_ASSIGNED = "RIDER_ASSIGNED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# For each status: which statuses it is allowed to move to next
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PLACED: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.RIDER_ASSIGNED, OrderStatus.CANCELLED},
    OrderStatus.RIDER_ASSIGNED: {OrderStatus.PICKED_UP},
    OrderStatus.PICKED_UP: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    """Return True if an order may move from `current` to `new`."""
    return new in ALLOWED_TRANSITIONS[current]