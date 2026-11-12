"""Build `dbmd` chunks and small ADM BWF files for tests (clean-room, stdlib).

The segment 9 and 10 layouts follow MediaInfoLib's reader (see
sentinel/dbmd.py); unread spans are filled with a recognisable byte (0xA5 by
default) so a reader that strays into them reads garbage, not zeroes.
"""

from __future__ import annotations

import struct

FILL = 0xA5


def checksum(size: int, payload: bytes, two_byte: bool = False) -> int:
    init = ((size & 0xFF) + (size >> 8)) if two_byte else (size & 0xFF)
    return (~((init + sum(payload)) & 0xFF) + 1) & 0xFF


def segment(sid: int, payload: bytes, *, bad_checksum: bool = False,
            two_byte_checksum: bool = False, declared_size: int | None = None) -> bytes:
    size = len(payload) if declared_size is None else declared_size
    cs = checksum(size, payload, two_byte_checksum)
    if bad_checksum:
        cs ^= 0x5A
    return bytes([sid]) + struct.pack("<H", size) + payload + bytes([cs])


def dbmd(segments: list[bytes], version: int = 0x01000000, terminate: bool = True) -> bytes:
    b = struct.pack("<I", version) + b"".join(segments) + (b"\0" if terminate else b"")
    return b


def segment9(*, tool: str = "Dolby Atmos Renderer", tool_version=(5, 2, 0),
             fps: int = 2, ffoa: tuple[int, int, int] | None = None,
             downmix5to2: int = 1, phase90: int = 0, warp: int = 0,
             bed_distribution: int = 0, extra: int = 0, fill: int = FILL) -> bytes:
    p = bytearray([fill]) * (168 + extra)
    p[32:96] = tool.encode("utf-8")[:64].ljust(64, b"\0")
    p[96:99] = bytes(tool_version)
    p[111] = (fill & 0xF0) | (fps & 0x0F)
    if ffoa is None:
        p[112], p[113] = 0xFF, fill
        p[114:118] = bytes([fill]) * 4
    else:
        hh, mm, ss = ffoa
        p[112], p[113] = hh & 0xFF, mm
        p[114:118] = struct.pack("<I", ss)
    p[139] = (fill & 0x8C) | ((downmix5to2 & 0x07) << 4) | (phase90 & 0x03)
    p[152] = ((bed_distribution & 0x03) << 6) | (fill & 0x38) | (warp & 0x07)
    return bytes(p)


def segment10(binaural: list[int], *, trims: list | None = None,
              trim_bypass: list[int] | None = None, head_track: list[int] | None = None,
              sync: int = 0xF8726FBD, object_count: int | None = None,
              extra: int = 0, fill: int = FILL) -> bytes:
    n = len(binaural) if object_count is None else object_count
    p = bytearray(struct.pack("<IH", sync, n)) + bytes([fill])
    trims = trims if trims is not None else ["auto"] * 9
    for t in trims:
        if t == "auto":
            p += bytes([(fill & 0xFE) | 1]) + bytes([fill]) * 14
        else:
            c, s, h, b1, b2 = t
            p += bytes([fill & 0xFE]) + struct.pack("<fff", c, s, h) + bytes([b1, b2])
    tb = trim_bypass if trim_bypass is not None else [0] * len(binaural)
    p += bytes([(fill & 0xFC) | (x & 0x03) for x in tb])
    ht = head_track if head_track is not None else [0] * len(binaural)
    p += bytes([((h & 0x03) << 6) | (fill & 0x38) | (m & 0x07)
                for m, h in zip(binaural, ht)])
    p += bytes([fill]) * extra
    return bytes(p)


def _chunk(cid: bytes, payload: bytes, size: int | None = None) -> bytes:
    sz = len(payload) if size is None else size
    return cid + struct.pack("<I", sz) + payload + (b"\0" if len(payload) & 1 else b"")


def adm_wav(*, channels: int = 2, rate: int = 48000, bits: int = 24, frames: int = 480,
            dbmd_payload: bytes | None = None, container: bytes = b"RIFF",
            chna_tracks: int | None = None, types: list[str] | None = None,
            junk: int | None = None, fmt_tag: int = 1, chna_uids: int | None = None,
            ds64_riff: int | None = None, bext: bool = False,
            drop: tuple[bytes, ...] = (), truncate: int = 0,
            chna_reversed: bool = False) -> bytes:
    """A minimal ADM-shaped WAVE: [JUNK], fmt, [bext], [dbmd], chna, axml (a stub), data.

    `types` gives each chna track's ADM type (the yyyy of AT_yyyyxxxx_nn:
    "0001" a bed channel, "0003" an object; default every track an object);
    `chna_uids` writes a numUIDs that differs from numTracks; `ds64_riff`
    declares a RIFF size in ds64 (a large one without writing the bytes);
    `drop` leaves chunks out; `truncate` cuts that many bytes off the end;
    `chna_reversed` lists the chna entries last track first (their track
    indices unchanged), which BS.2076 allows.
    """
    ba = channels * bits // 8
    fmt = struct.pack("<HHIIHH", fmt_tag, channels, rate, rate * ba, ba, bits)
    nt = channels if chna_tracks is None else chna_tracks
    types = types if types is not None else ["0003"] * nt
    nu = nt if chna_uids is None else chna_uids
    chna = struct.pack("<HH", nt, nu)
    for i in (reversed(range(nt)) if chna_reversed else range(nt)):
        ty = types[i] if i < len(types) else "0003"
        chna += (struct.pack("<H", i + 1) + f"ATU_{i + 1:08X}".encode()
                 + f"AT_{ty}{0x1001 + i:04X}_01".encode() + f"AP_{ty}{0x1001 + i:04X}".encode()
                 + b"\0")
    axml = b'<?xml version="1.0"?><ebuCoreMain><coreMetadata><format><audioFormatExtended version="ITU-R_BS.2076-2"/></format></coreMetadata></ebuCoreMain>'
    data = bytes(ba * frames)
    body = b""
    if junk is not None and container == b"RIFF":
        body += _chunk(b"JUNK", bytes(junk))
    if b"fmt " not in drop:
        body += _chunk(b"fmt ", fmt)
    if bext:
        body += _chunk(b"bext", bytes(602))
    if dbmd_payload is not None:
        body += _chunk(b"dbmd", dbmd_payload)
    if b"chna" not in drop:
        body += _chunk(b"chna", chna)
    if b"axml" not in drop:
        body += _chunk(b"axml", axml)
    if container == b"RIFF":
        body += _chunk(b"data", data)
        out = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body
        return out[:len(out) - truncate] if truncate else out
    ds64 = struct.pack("<QQQI", 0, len(data), frames, 0)
    head = _chunk(b"ds64", ds64)
    body = head + body + b"data" + struct.pack("<I", 0xFFFFFFFF) + data
    riff = 4 + len(body) if ds64_riff is None else ds64_riff
    body = _chunk(b"ds64", struct.pack("<QQQI", riff, len(data), frames, 0)) + body[len(head):]
    out = container + struct.pack("<I", 0xFFFFFFFF) + b"WAVE" + body
    return out[:len(out) - truncate] if truncate else out
