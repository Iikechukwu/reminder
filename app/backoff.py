"""Retry delay: exponential backoff with full jitter."""
import random
from typing import Callable


def backoff_delay(
    attempt: int,
    base: float,
    cap: float,
    rng: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait before the retry that follows failed attempt number `attempt`.

    ceiling = min(cap, base * 2**(attempt-1))   -> base, 2*base, 4*base, ... up to cap
    delay   = uniform(0, ceiling)                -> "full jitter"

    Exponential growth gives a struggling provider room to recover. Jitter
    spreads retries out so many jobs that failed together do not all retry at
    the same instant (a "thundering herd"). `rng` returns a float in [0, 1) and
    is injectable so tests are deterministic.
    """
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    # Clamp the exponent: avoids producing astronomically large ints.
    ceiling = min(cap, base * (2 ** min(attempt - 1, 62)))
    return rng() * ceiling
