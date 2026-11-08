from order_status import ALLOWED_TRANSITIONS, OrderStatus, can_transition


def test_placed_order_can_be_accepted():
    assert can_transition(OrderStatus.PLACED, OrderStatus.ACCEPTED)


def test_placed_order_cannot_jump_to_delivered():
    assert not can_transition(OrderStatus.PLACED, OrderStatus.DELIVERED)


def test_delivered_order_cannot_change_any_more():
    for status in OrderStatus:
        assert not can_transition(OrderStatus.DELIVERED, status)


def test_full_happy_path_is_allowed():
    path = [
        OrderStatus.PLACED,
        OrderStatus.ACCEPTED,
        OrderStatus.RIDER_ASSIGNED,
        OrderStatus.PICKED_UP,
        OrderStatus.DELIVERED,
    ]
    for current, new in zip(path, path[1:]):
        assert can_transition(current, new), f"{current} -> {new} should be allowed"


def test_every_status_has_rules():
    assert set(ALLOWED_TRANSITIONS) == set(OrderStatus)