"""Walk an ADM BWF master's chunks: RIFF, RF64 or BW64 (with `ds64`).

Stdlib only, and it never reads the audio: chunks are found by seeking, and
only `ds64`, `fmt `, `chna` and `dbmd` are read into memory (`axml` only its
size). It answers the structural questions a delivery check asks first --
which container, which chunks, what PCM format, how many tracks `chna` names
-- and hands the `dbmd` bytes to `sentinel.dbmd`.
"""

from __future__ import annotations

import os
import struct
from typing import Any

from .dbmd import parse_dbmd

CONTAINERS = (b"RIFF", b"RF64", b"BW64")
_READ = {b"ds64", b"fmt ", b"chna", b"dbmd"}
_MAX_READ = 64 << 20   # a metadata chunk larger than this is reported, not read


def read_chunks(path: str) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path, "notes": []}
    with open(path, "rb") as f:
        hdr = f.read(12)
        fsize = os.fstat(f.fileno()).st_size
        if len(hdr) < 12 or hdr[:4] not in CONTAINERS or hdr[8:12] != b"WAVE":
            out["container"] = None
            out["notes"].append("not a RIFF/RF64/BW64 WAVE file")
            return out
        out["container"] = hdr[:4].decode()
        out["fileSize"] = fsize
        out["riffSize"] = struct.unpack_from("<I", hdr, 4)[0]
        chunks: list[dict[str, Any]] = []
        bodies: dict[str, bytes] = {}
        ds64_riff = ds64_data = None
        pos = 12
        while pos + 8 <= fsize:
            f.seek(pos)
            h = f.read(8)
            cid, size = h[:4], struct.unpack_from("<I", h, 4)[0]
            name = cid.decode("latin-1")
            real = size
            if size == 0xFFFFFFFF and out["container"] != "RIFF":
                if cid == b"data" and ds64_data is not None:
                    real = ds64_data
                elif cid not in (b"data",):
                    out["notes"].append(f"chunk {name!r} uses the 64-bit size sentinel; "
                                        "its ds64 table entry is not read")
            ent = {"id": name, "offset": pos, "size": real}
            if pos + 8 + real > fsize:
                ent["truncated"] = True
                out["notes"].append(f"chunk {name!r} runs {pos + 8 + real - fsize} bytes past the end")
            chunks.append(ent)
            if cid in _READ and name not in bodies:
                if real <= _MAX_READ:
                    bodies[name] = f.read(min(real, fsize - pos - 8))
                else:
                    out["notes"].append(f"chunk {name!r} of {real} bytes not read")
            if cid == b"ds64" and len(bodies.get("ds64", b"")) >= 24:
                ds64_riff, ds64_data = struct.unpack_from("<QQ", bodies["ds64"], 0)
            pos += 8 + real + (real & 1)
        out["chunks"] = chunks
        if ds64_riff is not None:
            out["ds64"] = {"riffSize": ds64_riff, "dataSize": ds64_data}
        out["_bodies"] = bodies
    return out


def _fmt(b: bytes) -> dict[str, Any] | None:
    if len(b) < 16:
        return None
    tag, ch, rate, _br, _ba, bits = struct.unpack_from("<HHIIHH", b, 0)
    return {"formatTag": tag, "channels": ch, "sampleRate": rate, "bitDepth": bits}


def _chna(b: bytes) -> dict[str, Any] | None:
    if len(b) < 4:
        return None
    nt, nu = struct.unpack_from("<HH", b, 0)
    tracks = []
    for i in range(nu):
        o = 4 + 40 * i
        if o + 40 > len(b):
            break
        ti = struct.unpack_from("<H", b, o)[0]
        fld = lambda a, w: b[o + a:o + a + w].split(b"\0", 1)[0].decode("ascii", "replace")
        tracks.append({"trackIndex": ti, "uid": fld(2, 12), "trackRef": fld(14, 14),
                       "packRef": fld(28, 11)})
    return {"numTracks": nt, "numUIDs": nu, "tracks": tracks}


def adm_info(path: str) -> dict[str, Any]:
    """Container, chunks, PCM format, `chna` and the decoded `dbmd`, as one dict."""
    raw = read_chunks(path)
    bodies = raw.pop("_bodies", {})
    info: dict[str, Any] = dict(raw)
    info["format"] = _fmt(bodies.get("fmt ", b""))
    info["chna"] = _chna(bodies.get("chna", b""))
    ids = [c["id"] for c in raw.get("chunks", [])]
    info["isAdm"] = "axml" in ids and "chna" in ids
    if "dbmd" in bodies:
        d = parse_dbmd(bodies["dbmd"])
        sup = d.get("supplemental") or {}
        modes = sup.get("binaural")
        if modes is not None:
            # As MediaInfoLib does: the n-th entry is the n-th audio track.
            uid_by_track = {t["trackIndex"]: t["uid"] for t in (info["chna"] or {}).get("tracks", [])}
            for m in modes:
                m["chnaTrackIndex"] = m["index"] + 1
                m["uid"] = uid_by_track.get(m["index"] + 1)
            nch = (info["format"] or {}).get("channels")
            if nch and sup.get("objectCount") != nch:
                d["notes"].append(f"segment 10 names {sup.get('objectCount')} tracks; "
                                  f"fmt has {nch} channels")
        info["dolbyMetadata"] = d
    else:
        info["dolbyMetadata"] = None
    return info


def render_text(info: dict[str, Any]) -> str:
    L = [f"{info['path']}"]
    if not info.get("container"):
        return "\n".join(L + ["  not a RIFF/RF64/BW64 WAVE file"])
    fm = info.get("format") or {}
    L.append(f"  container {info['container']}, {info.get('fileSize')} bytes; "
             f"chunks: {', '.join(c['id'].strip() for c in info.get('chunks', []))}")
    if fm:
        L.append(f"  PCM format tag {fm['formatTag']}, {fm['channels']} ch, "
                 f"{fm['sampleRate']} Hz, {fm['bitDepth']}-bit")
    ch = info.get("chna")
    if ch:
        L.append(f"  chna: {ch['numTracks']} tracks, {ch['numUIDs']} UIDs")
    d = info.get("dolbyMetadata")
    if d is None:
        L.append("  dbmd: absent")
    else:
        L.append(f"  dbmd: {d['size']} bytes, version {d.get('version', '?')}, "
                 f"segments {[s['id'] for s in d['segments']] or 'none'}")
        a = d.get("atmos")
        if a and "frameRate" in a:
            f = a["firstFrameOfAction"]
            L.append(f"    frame rate {a['frameRate']['name']}; first frame of action "
                     f"{'unassigned' if f is None else '%.5f s' % f['seconds']}")
            L.append(f"    5.1.x downmix {a['downmix5_1x']['name']}; 5.1 to 2.0 "
                     f"{a['downmix5to2']['name']}, {a['phaseShift90_5to2']['name']}")
            L.append(f"    written by {a['contentCreationTool'] or '(blank)'} "
                     f"{a['contentCreationToolVersion']}")
        s = d.get("supplemental")
        if s and "binaural" in s:
            counts: dict[str, int] = {}
            for m in s["binaural"]:
                counts[m["name"]] = counts.get(m["name"], 0) + 1
            L.append("    headphone render modes: " +
                     ", ".join(f"{k} x{v}" for k, v in counts.items()))
        if s and "trims" in s:
            L.append("    trims: " + ", ".join(
                f"{t['config']}:{'auto' if t['auto'] else 'manual'}" for t in s["trims"]))
        for n in d["notes"] + [n for x in (a, s) if x for n in x.get("notes", [])]:
            L.append(f"    note: {n}")
        L.append(f"    ({d['basis']})")
    for n in info.get("notes", []):
        L.append(f"  note: {n}")
    return "\n".join(L)
