"""Read Dolby's metadata chunk (`dbmd`) from an ADM BWF master.

Stdlib only. The chunk's framing is public: EBU Tech 3285 Supplement 6 (2009)
gives a 32-bit version word, then segments of a one-byte id, a two-byte size,
the payload and a one-byte checksum, ended by a segment id of 0; every
multi-byte field little-endian. It lists ids 0-8; Dolby Atmos masters carry
two later ones, 9 ("Dolby Atmos Metadata") and 10 ("Dolby Atmos Supplemental
Metadata"), whose layout Dolby has not published.

The field positions used here for segments 9 and 10 are MediaInfoLib's
reading (`Source/MediaInfo/Audio/File_DolbyAudioMetadata.cpp`, BSD-2, read at
349e786 on 2026-11-12): a third-party reader that skips the spans it does not
understand. So this module reads the fields a delivery specification names --
frame rate, first frame of action, the 5.1-to-2.0 downmix and its phase
shift, the 5.1.x downmix ("warp mode"), the trim configurations and every
track's headphone (binaural) render mode -- and nothing else. It has not yet
been checked against a master written by Dolby's own renderer; until it has,
every decoded value carries that caveat (`basis` in the result).

Bit fields are read most-significant bit first, as MediaInfoLib's bit reader
does.
"""

from __future__ import annotations

import struct
from typing import Any

BASIS = ("segments 9 and 10 decoded by MediaInfoLib's field map "
         "(File_DolbyAudioMetadata.cpp); not yet confirmed on a master "
         "written by Dolby's renderer")

SEGMENT_NAMES = {
    0: "end",
    1: "Dolby E Metadata",
    3: "Dolby Digital Metadata",
    7: "Dolby Digital Plus Metadata",
    8: "Audio Info",
    9: "Dolby Atmos Metadata",
    10: "Dolby Atmos Supplemental Metadata",
}

# Tables, in code order. The binaural order is the trap: 2 is Far, 3 is Mid.
FRAME_RATES = [None, (24 / 1.001, False), (24.0, False), (25.0, False),
               (30 / 1.001, True), (30 / 1.001, False), (30.0, False)]
FRAME_RATE_NAMES = ["not indicated", "23.976", "24", "25", "29.97 DF",
                    "29.97 NDF", "30"]
DOWNMIX_5TO2 = ["not indicated (Lo/Ro)", "Lo/Ro", "Lt/Rt (Dolby Pro Logic)",
                "Lt/Rt (Dolby Pro Logic II)", "direct stereo render"]
PHASE_90_5TO2 = ["without 90-degree phase shift", "with 90-degree phase shift"]
WARP_MODES = ["Direct Render", "Direct Render with room balance",
              "Dolby Pro Logic IIx", "Standard (Lo/Ro)", "not indicated"]
BINAURAL_MODES = ["Off", "Near", "Far", "Mid", "not indicated (Mid)"]
TRIM_BYPASS = ["trim applied", "trim ignored", "not indicated"]

ATMOS_SYNC = 0xF8726FBD
SEG9_MIN = 168          # bytes MediaInfoLib reads from segment 9
TRIM_CONFIGS = 9
TRIM_CONFIG_BYTES = 15  # one flag byte + 14 (manual: three float32 and two bytes)


def _name(table: list, code: int) -> str:
    return table[code] if 0 <= code < len(table) else f"unknown ({code})"


def checksum(size: int, payload: bytes) -> tuple[int, int]:
    """Both readings of Tech 3285 s6 section 3.3: (low byte of size, both size bytes).

    The text initialises the sum with "the metadata_segment_size byte"; its
    pseudocode starts from the size value, whose carries the mask discards, so
    only the low byte counts. A two-byte-sum reading is reported beside it
    until a Dolby-written chunk shows which one Dolby computes.
    """
    a = size & 0xFF
    b = ((size & 0xFF) + (size >> 8)) & 0xFF
    s = sum(payload) & 0xFF
    return ((~(a + s) + 1) & 0xFF), ((~(b + s) + 1) & 0xFF)


def _version_text(v: int) -> str:
    return f"{v >> 24}.{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


def parse_segment9(p: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"notes": []}
    if len(p) < SEG9_MIN:
        out["notes"].append(f"segment 9 is {len(p)} bytes; the field map reads {SEG9_MIN}")
        return out
    tool = p[32:96].split(b"\0", 1)[0].decode("utf-8", "replace")
    tv = int.from_bytes(p[96:99], "big")
    fps = p[111] & 0x0F
    hh, mm = p[112], p[113]
    ss = struct.unpack_from("<I", p, 114)[0]
    dm = (p[139] >> 4) & 0x07
    ph = p[139] & 0x03
    bed_dist = (p[152] >> 6) & 0x03
    warp = p[152] & 0x07
    rate = FRAME_RATES[fps] if fps < len(FRAME_RATES) else None
    if hh == 0xFF:
        ffoa = None
    else:
        neg = hh >= 0x80
        h = (256 - hh) if neg else hh
        secs = h * 3600 + mm * 60 + ss / 100000.0
        ffoa = {"hh": h, "mm": mm, "ss100k": ss, "negative": neg,
                "seconds": -secs if neg else secs}
    out.update({
        "contentCreationTool": tool,
        "contentCreationToolVersion": f"{tv >> 16}.{(tv >> 8) & 0xFF}.{tv & 0xFF}",
        "frameRate": {"code": fps, "name": _name(FRAME_RATE_NAMES, fps),
                      "fps": round(rate[0], 6) if rate else None,
                      "dropFrame": rate[1] if rate else None},
        "firstFrameOfAction": ffoa,
        "downmix5to2": {"code": dm, "name": _name(DOWNMIX_5TO2, dm)},
        "phaseShift90_5to2": {"code": ph, "name": _name(PHASE_90_5TO2, ph)},
        "downmix5_1x": {"code": warp, "name": _name(WARP_MODES, warp)},
        "bedDistribution": bed_dist,
    })
    if len(p) > SEG9_MIN:
        out["notes"].append(f"{len(p) - SEG9_MIN} bytes after the mapped fields not read")
    return out


def parse_segment10(p: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"notes": []}
    if len(p) < 4:
        out["syncOk"] = False
        out["notes"].append("segment 10 too short for its sync word")
        return out
    sync = struct.unpack_from("<I", p, 0)[0]
    out["syncOk"] = sync == ATMOS_SYNC
    if not out["syncOk"]:
        out["notes"].append(f"sync word 0x{sync:08X}, expected 0x{ATMOS_SYNC:08X}: not read")
        return out
    need = 7 + TRIM_CONFIGS * TRIM_CONFIG_BYTES
    if len(p) < need:
        out["notes"].append(f"segment 10 is {len(p)} bytes; its trim block needs {need}")
        return out
    n = struct.unpack_from("<H", p, 4)[0]
    out["objectCount"] = n
    trims = []
    o = 7
    for cfg in range(TRIM_CONFIGS):
        auto = bool(p[o] & 0x01)
        t: dict[str, Any] = {"config": cfg, "auto": auto}
        if not auto:
            c, s, h = struct.unpack_from("<fff", p, o + 1)
            b1, b2 = p[o + 13], p[o + 14]
            t.update({"centreDb": round(c, 4), "surroundDb": round(s, 4),
                      "heightDb": round(h, 4),
                      "balanceOverheadFloor": round((-1 if b1 & 0x80 else 1) * (b1 & 0x7F) / 127, 4),
                      "balanceListener": round((-1 if b2 & 0x80 else 1) * (b2 & 0x7F) / 127, 4)})
        trims.append(t)
        o += TRIM_CONFIG_BYTES
    out["trims"] = trims
    if len(p) < o + 2 * n:
        out["notes"].append(f"segment 10 is {len(p)} bytes; {n} tracks need {o + 2 * n}")
        return out
    out["trimBypass"] = [{"index": i, "code": p[o + i] & 0x03,
                          "name": _name(TRIM_BYPASS, p[o + i] & 0x03)} for i in range(n)]
    o += n
    out["binaural"] = [{"index": i, "code": p[o + i] & 0x07,
                        "name": _name(BINAURAL_MODES, p[o + i] & 0x07),
                        "headTrackMode": (p[o + i] >> 6) & 0x03} for i in range(n)]
    o += n
    if len(p) > o:
        out["notes"].append(f"{len(p) - o} bytes after the mapped fields not read")
    return out


def parse_dbmd(chunk: bytes) -> dict[str, Any]:
    """Decode a `dbmd` chunk's payload (the bytes after its 8-byte header)."""
    r: dict[str, Any] = {"present": True, "size": len(chunk), "basis": BASIS,
                         "segments": [], "terminated": False,
                         "atmos": None, "supplemental": None, "notes": []}
    if len(chunk) < 4:
        r["readable"] = False
        r["notes"].append("shorter than its version word")
        return r
    v = struct.unpack_from("<I", chunk, 0)[0]
    r["version"] = _version_text(v)
    if (v >> 24) > 1:
        r["readable"] = False
        r["notes"].append(f"version {r['version']}: major version above 1 is not read")
        return r
    r["readable"] = True
    o = 4
    while o < len(chunk):
        sid = chunk[o]
        o += 1
        if sid == 0:
            r["terminated"] = True
            break
        if o + 2 > len(chunk):
            r["notes"].append(f"segment {sid}: no room for its size field")
            break
        size = struct.unpack_from("<H", chunk, o)[0]
        o += 2
        room = max(len(chunk) - o - 1, 0)
        seg: dict[str, Any] = {"id": sid, "name": SEGMENT_NAMES.get(sid, "reserved"),
                               "size": size}
        if size == 0:
            size = 65535
            seg["notes"] = ["size 0 read as 65535 (Tech 3285 s6)"]
        if size > room:
            seg.setdefault("notes", []).append(f"declares {size} bytes, {room} remain")
            size = room
        payload = chunk[o:o + size]
        o += size
        if o < len(chunk):
            got = chunk[o]
            o += 1
            low, two = checksum(seg["size"], payload)
            seg["checksum"] = ("ok" if got == low else
                               "ok (two-byte size reading)" if got == two else
                               f"mismatch (0x{got:02X}; 0x{low:02X} expected)")
        else:
            seg["checksum"] = "missing"
        r["segments"].append(seg)
        if sid == 9 and r["atmos"] is None:
            r["atmos"] = parse_segment9(payload)
        elif sid == 10 and r["supplemental"] is None:
            r["supplemental"] = parse_segment10(payload)
    if not r["terminated"]:
        r["notes"].append("no end segment (id 0)")
    return r
