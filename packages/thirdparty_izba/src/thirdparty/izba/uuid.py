#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

"""UUIDv7 (RFC 9562) for Python 3.9+, standard library only.

Layout (128 bits):
    48 bits  unix timestamp in milliseconds
     4 bits  version (0b0111)
    12 bits  rand_a
     2 bits  variant (0b10)
    62 bits  rand_b

rand_a + rand_b form a 74-bit field. Within the same millisecond it is
incremented rather than re-randomised, so IDs from one process are strictly
increasing even when many are generated per millisecond or the clock steps back.
"""

import os
import threading
import time
import uuid

_RAND_BITS = 74
_RAND_MASK = (1 << _RAND_BITS) - 1
_lock = threading.Lock()
_last_ms = -1
_last_rand = 0


def _fresh_rand() -> int:
    # Clear the top bit to leave headroom for the in-millisecond counter.
    return int.from_bytes(os.urandom(10), "big") & (_RAND_MASK >> 1)


def uuid7() -> uuid.UUID:
    global _last_ms, _last_rand
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            rand = _fresh_rand()
        else:
            # Same millisecond, or the clock went backwards: keep the old
            # timestamp and increment so ordering is preserved.
            ms = _last_ms
            rand = _last_rand + 1
            if rand > _RAND_MASK:  # counter exhausted, move to the next ms
                ms += 1
                rand = _fresh_rand()
        _last_ms, _last_rand = ms, rand

    rand_a = rand >> 62
    rand_b = rand & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(u: uuid.UUID) -> int:
    """Extract the embedded unix timestamp (ms) from a UUIDv7."""
    return u.int >> 80


if __name__ == "__main__":
    print(uuid7())