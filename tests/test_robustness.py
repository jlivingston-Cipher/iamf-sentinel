"""Item 22 (doc 84): robustness / bounded-fuzz acceptance for L1/L2 + the
container walk.

Acceptance (doc 82 §5 step 3): no hangs, no uncaught exceptions — every
malformed input yields a structured Report (findings or a captured
`execution_error`), never a traceback out of `validate_bytes` and never a
run past a per-case wall-clock bound.

The seed corpus is the 7 valid specs, their MP4 wraps, and the 25
mutation-class outputs; the mutators are bit flips, truncation,
length-field smashes, and byte splices, driven by a FIXED seed so the run
is deterministic and CI-stable. Kept small enough for the unit suite; the
full multi-thousand-per-seed campaign lives in the doc-84 evidence, not
here.

`test_stsz_constant_count_is_bounded` is the named regression for the DoS
the campaign found: a constant-size `stsz` whose sample_count field is
smashed to 2^31 made the walk allocate `[size] * 2**31` and hang ~2 minutes
before the fix (mp4.py `_MAX_TABLE_ENTRIES` + the `len(data)` clamp).
"""

from __future__ import annotations

import random
import signal
import struct
import time

import pytest

from fixtures import build as B
from fixtures.mp4wrap import wrap_mp4
from fixtures.mutate import MUTATIONS
from sentinel.container.mp4 import parse_mp4
from sentinel.engine import validate_bytes
from sentinel.parser import parse_bytes

PER_CASE_TIMEOUT_S = 2.0
ITERS_PER_SEED = 60          # 53 seeds x 60 x 3 entry points ~ 9.5k guarded calls


class _Timeout(Exception):
    pass


def _install_alarm():
    if not hasattr(signal, "setitimer"):
        pytest.skip("itimer unavailable on this platform")
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_Timeout()))


def _seeds() -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for name, spec in B.all_valid_specs().items():
        raw = B.build(spec)
        out.append((f"valid/{name}", raw))
        out.append((f"wrap/{name}", wrap_mp4(raw)))
        out.append((f"trim/{name}",
                    wrap_mp4(raw, elst=[(0, 312)], stts=[(1, 1), (1, 959)])))
    for mut in MUTATIONS:
        out.append((f"mut/{mut.label}", mut.build_fn()))
    return out


def _mutate(data: bytes, rng: random.Random) -> bytes:
    if not data:
        return rng.randbytes(rng.randint(0, 32))
    b = bytearray(data)
    kind = rng.randint(0, 6)
    if kind == 0:
        b[rng.randrange(len(b))] ^= 1 << rng.randint(0, 7)
    elif kind == 1:
        for _ in range(rng.randint(2, 16)):
            b[rng.randrange(len(b))] ^= 1 << rng.randint(0, 7)
    elif kind == 2:
        return bytes(b[:rng.randrange(len(b) + 1)])
    elif kind == 3 and len(b) >= 4:
        i = rng.randrange(len(b) - 3)
        b[i:i + 4] = rng.choice([b"\xff\xff\xff\xff", b"\x00\x00\x00\x00",
                                 b"\x7f\xff\xff\xff", b"\x00\x00\x00\x01"])
    elif kind == 4:
        i = rng.randrange(len(b) + 1)
        b[i:i] = rng.randbytes(rng.randint(1, 24))
    elif kind == 5:
        i = rng.randrange(len(b))
        n = rng.randint(1, min(24, len(b) - i))
        b[i:i + n] = rng.randbytes(n)
    else:
        n = min(rng.randint(1, 16), len(b))
        b[:n] = b"\x00" * n
    return bytes(b)


def test_bounded_fuzz_no_hang_no_crash():
    _install_alarm()
    rng = random.Random(0xF32C0DE)
    seeds = _seeds()
    slowest = 0.0
    entry_points = (
        ("validate", lambda d: validate_bytes(d, source="fuzz")),
        ("parse_mp4", parse_mp4),
        ("parse_bytes", lambda d: parse_bytes(d, source="fuzz",
                                              container="raw")),
    )
    try:
        cases = [d for _, d in seeds]
        cases += [_mutate(d, rng) for _, d in seeds
                  for _ in range(ITERS_PER_SEED)]
        for data in cases:
            for tag, fn in entry_points:
                signal.setitimer(signal.ITIMER_REAL, PER_CASE_TIMEOUT_S)
                t0 = time.time()
                try:
                    fn(data)
                except _Timeout:
                    pytest.fail(f"{tag} exceeded {PER_CASE_TIMEOUT_S}s "
                                f"on a {len(data)}-byte input")
                except Exception as e:
                    # parse_mp4 / parse_bytes are internal and MAY raise
                    # (validate_bytes guards them); only the public API is
                    # held to the never-raise contract.
                    if tag == "validate":
                        pytest.fail(f"validate_bytes raised {type(e).__name__}"
                                    f": {e}")
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                slowest = max(slowest, time.time() - t0)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert slowest < PER_CASE_TIMEOUT_S


def _mp4_with_stsz(sample_count: int, sample_size: int) -> bytes:
    """A structurally walkable MP4 whose stsz declares a constant sample
    size and an arbitrary (here: hostile) sample_count."""
    def box(fourcc, payload):
        return struct.pack(">I", 8 + len(payload)) + fourcc + payload

    stsz = box(b"stsz", struct.pack(">IIII", 0, sample_size, sample_count, 0))
    stco = box(b"stco", struct.pack(">II", 1, 0))
    stsc = box(b"stsc", struct.pack(">I", 0))
    stsd = box(b"stsd", struct.pack(">I", 0)
               + struct.pack(">I", 1) + box(b"iamf", b"\x00" * 8))
    stbl = box(b"stbl", stsd + stsz + stsc + stco)
    minf = box(b"minf", stbl)
    mdhd = box(b"mdhd", b"\x00" * 12 + struct.pack(">I", 48000)
               + struct.pack(">I", 0) + b"\x00" * 4)
    mdia = box(b"mdia", mdhd + minf)
    trak = box(b"trak", mdia)
    moov = box(b"moov", trak)
    ftyp = box(b"ftyp", b"iamf" + b"\x00" * 4 + b"iamf")
    return ftyp + moov


def test_stsz_constant_count_is_bounded():
    """Named regression: a smashed constant-size stsz sample_count must not
    materialize an unbounded list. Bounded parse in well under a second."""
    _install_alarm()
    hostile = _mp4_with_stsz(sample_count=0x7FFFFFFF, sample_size=4)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    t0 = time.time()
    try:
        info = parse_mp4(hostile)
    except _Timeout:
        pytest.fail("constant-size stsz sample_count is still unbounded")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert time.time() - t0 < 1.0
    track = info.tracks[0]
    # clamped to at most the file length, never the declared 2^31
    assert len(track.sample_sizes) <= len(hostile)
