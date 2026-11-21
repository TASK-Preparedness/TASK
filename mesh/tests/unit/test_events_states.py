# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import pytest

from task_mesh.core.events import EventBus
from task_mesh.domain.states import (
    TRANSITIONS,
    Badge,
    ConnectionState as S,
    StateMachine,
    badge_for,
    is_legal,
)
from task_mesh.services.backoff import Backoff


class Base:
    pass


class Child(Base):
    pass


def test_event_bus_dispatch_by_type_and_mro():
    bus, got = EventBus(), []
    bus.subscribe(Base, lambda e: got.append(("base", type(e).__name__)))
    bus.subscribe(Child, lambda e: got.append(("child", type(e).__name__)))
    assert bus.publish(Child()) == 2
    assert bus.publish(Base()) == 1
    assert ("base", "Child") in got and ("child", "Child") in got


def test_event_bus_isolates_failing_handler_and_unsubscribe():
    bus, got = EventBus(), []

    def bad(_):
        raise RuntimeError("boom")

    good = got.append
    bus.subscribe(Base, bad)
    bus.subscribe(Base, good)
    assert bus.publish(Base()) == 1 and len(got) == 1
    bus.unsubscribe(Base, good)
    bus.unsubscribe(Base, good)  # idempotent
    assert bus.publish(Base()) == 0


def test_every_state_has_a_transition_row_and_badge():
    for st in S:
        assert st in TRANSITIONS
        assert isinstance(badge_for(st), Badge)
    assert badge_for(S.CONNECTED) is Badge.CONNECTED
    assert badge_for(S.DEVICE_REBOOTING) is Badge.CONNECTING
    assert badge_for(S.BACKOFF) is Badge.DISCONNECTED


@pytest.mark.parametrize("src,dst", [(s, d) for s, ds in TRANSITIONS.items() for d in ds])
def test_all_legal_transitions_apply(src, dst):
    seen = []
    sm = StateMachine(src, lambda a, b, r: seen.append((a, b, r)))
    assert sm.transition(dst, "r") is True
    assert sm.state is dst and seen == [(src, dst, "r")]


def test_illegal_transitions_are_ignored_not_raised():
    sm = StateMachine(S.IDLE)
    assert not is_legal(S.IDLE, S.CONNECTED)
    assert sm.transition(S.CONNECTED) is False
    assert sm.state is S.IDLE and sm.history == []
    assert sm.transition(S.IDLE) is False  # self-transition is a no-op


def test_design_paths_are_legal():
    path = [S.IDLE, S.SCANNING, S.CONNECTING, S.CONNECTED, S.DEVICE_REBOOTING, S.CONNECTED,
            S.DISCONNECTING, S.BACKOFF, S.SCANNING, S.NO_DEVICE, S.SCANNING, S.AWAITING_SELECTION,
            S.CONNECTING, S.PORT_BUSY, S.BACKOFF, S.SCANNING, S.PERMISSION_DENIED, S.SCANNING]
    for a, b in zip(path, path[1:]):
        assert is_legal(a, b), (a, b)


def test_backoff_schedule_and_cap():
    b = Backoff(rand=lambda: 0.5)  # zero jitter at midpoint
    assert [b.next_delay() for _ in range(8)] == [1, 2, 4, 8, 16, 30, 30, 30]
    b.reset()
    assert b.next_delay() == 1


def test_backoff_jitter_bounds():
    lo = Backoff(rand=lambda: 0.0)
    hi = Backoff(rand=lambda: 0.999999)
    for _ in range(6):
        n = lo.nominal(lo.attempt)
        assert lo.next_delay() == pytest.approx(n * 0.8)
        assert hi.next_delay() == pytest.approx(n * 1.2, rel=1e-4)
