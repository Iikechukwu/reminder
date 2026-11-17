import pytest

from app.backoff import backoff_delay

BASE, CAP = 10.0, 100.0
ALMOST_ONE = 0.9999999999


def test_ceiling_doubles_each_attempt_until_cap():
    ceilings = [backoff_delay(a, BASE, CAP, rng=lambda: ALMOST_ONE) for a in range(1, 8)]
    assert [round(c) for c in ceilings] == [10, 20, 40, 80, 100, 100, 100]


def test_jitter_scales_the_ceiling():
    assert backoff_delay(3, BASE, CAP, rng=lambda: 0.0) == 0.0
    assert backoff_delay(3, BASE, CAP, rng=lambda: 0.5) == pytest.approx(20.0)  # half of 40


def test_delay_never_exceeds_cap():
    for attempt in (1, 5, 10, 100, 10_000):
        assert backoff_delay(attempt, BASE, CAP, rng=lambda: ALMOST_ONE) <= CAP


def test_default_rng_stays_within_bounds_and_varies():
    delays = [backoff_delay(3, BASE, CAP) for _ in range(200)]
    assert all(0 <= d < 40 for d in delays)
    assert len(set(delays)) > 100  # real jitter, not a constant


def test_attempt_must_be_positive():
    with pytest.raises(ValueError):
        backoff_delay(0, BASE, CAP)
