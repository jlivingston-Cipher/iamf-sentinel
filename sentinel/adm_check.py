"""Judge an ADM BWF master against Dolby's published delivery rules.

    sentinel adm-check MASTER|FOLDER ... [--album] [--gapless]
                       [--format text|json|html] [-o OUT] [--strict]

Stdlib only, and it never reads the audio: everything here comes from the
file's chunks (`sentinel.bwf`) and Dolby's metadata block (`sentinel.dbmd`).
Each rule of two public Dolby documents gets one row and one of four
verdicts:

    PASS            the file meets the rule
    FAIL            a MUST (or a profile "shall") is broken
    WARN            a SHOULD is not met, or the file says nothing where the
                    rule expects a setting
    UNDETERMINED    the rule cannot be judged from this file by this tool:
                    it needs a measurement of the audio, a file beside the
                    master (the stereo master), or an XML reading this
                    release does not make. Never counted as a pass.

The rule levels are the documents' own words (MUST -> FAIL, SHOULD -> WARN);
no threshold here is this tool's invention. The documents:

  * Dolby Atmos Music Master Delivery Specification, v2022.07 (15 July 2022):
    its master, synchronization, loudness and gapless-album sections.
  * Dolby Atmos Master ADM Profile, v1.1 (5 January 2022): section 5 (the
    `dbmd` block) and section 7 (the BWF rules). Its XML rules (sections 2-4)
    are not judged by this release.

Rows S-511..S-515 read Dolby's metadata block with a third-party field map
(see `sentinel.dbmd.BASIS`); their verdicts carry that caveat. Rows S-520..
S-523 and the album's S-533/S-534 need a measurement or a second file and
are reported UNDETERMINED until those checks exist. A PASS here is not
Dolby certification, and this tool is not affiliated with Dolby.
"""

from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass, field
from typing import Any

from .bwf import adm_info
from .dbmd import BASIS
from .findings import REGISTRY

DELIVERY = "Dolby Atmos Music Master Delivery Specification v2022.07"
PROFILE = "Dolby Atmos Master ADM Profile v1.1"

PASS, FAIL, WARN, UNDET = "PASS", "FAIL", "WARN", "UNDETERMINED"
_RANK = {PASS: 0, UNDET: 0, WARN: 1, FAIL: 2}

FOUR_GB = 1 << 32
MAX_CHANNELS = 128
MAX_OBJECTS = 118
MAX_SMALL_CHUNK = 64        # JUNK under 4 GB, ds64 at 4 GB or more (profile 7.2)
TYPE_NAMES = {"0001": "DirectSpeakers", "0002": "Matrix", "0003": "Objects",
              "0004": "HOA", "0005": "Binaural"}
MASTER_EXTS = (".wav", ".bwf", ".rf64", ".w64")


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    level: str          # "MUST" | "SHOULD" | "shall" (profile) | "measured"
    source: str
    remedy: str


RULES: dict[str, Rule] = {}


def _rule(rid: str, level: str, source: str, remedy: str) -> None:
    # The title is the registry's (sentinel.findings), so `sentinel checks`
    # and this report can never name a rule two ways.
    RULES[rid] = Rule(rid, REGISTRY[rid].title, level, source, remedy)


# -- the master -------------------------------------------------------------
_rule("S-501", "MUST",
      f"{DELIVERY}, master; {PROFILE} 7",
      "Export the master as ADM BWF from the renderer; re-export if a chunk is "
      "cut short (the file was truncated in transfer).")
_rule("S-502", "shall", f"{PROFILE} 7.1",
      "Export as plain PCM; the profile does not accept WAVE_FORMAT_EXTENSIBLE "
      "or a compressed format tag.")
_rule("S-503", "MUST", f"{DELIVERY}, master; {PROFILE} 7.1",
      "Reduce the bed and object count so the master carries 128 channels or fewer.")
_rule("S-504", "MUST",
      f"{DELIVERY}, master; {PROFILE} 2.1.1, 2.4",
      "Merge or remove objects to 118 or fewer; tracks must be DirectSpeakers "
      "(bed) or Objects.")
_rule("S-505", "MUST", f"{DELIVERY}, master; {PROFILE} 7.1",
      "Export at 24-bit.")
_rule("S-506", "MUST", f"{DELIVERY}, master",
      "Deliver the ADM master at 48 kHz; the specification archives a 96 kHz "
      "project as a Dolby Atmos Master File set, not as the delivery ADM.")
_rule("S-507", "shall",
      f"{PROFILE} 7.1",
      "Re-export so a file of 4 GB or more is written as RF64 (EBU Tech 3306).")
_rule("S-508", "shall",
      f"{PROFILE} 7.2",
      "Re-export; the chna table must give each audio track exactly one UID.")
_rule("S-509", "shall", f"{PROFILE} 7.2",
      "Re-export with a writer that reserves no more than 64 bytes of padding.")
_rule("S-510", "profile", f"{PROFILE} 5",
      "Export from the Dolby Atmos Renderer, or add the block with a tool that "
      "writes it; without it the settings below cannot be read.")
_rule("S-511", "MUST", f"{DELIVERY}, synchronization",
      "Set the session's frame rate to 24 fps before exporting.")
_rule("S-512", "MUST", f"{DELIVERY}, synchronization",
      "Clear the first-frame-of-action marker in the renderer and re-export.")
_rule("S-513", "SHOULD", f"{DELIVERY}, master",
      "Set the 5.1 and 5.1.x downmix to Direct Render.")
_rule("S-514", "SHOULD", f"{DELIVERY}, master",
      "Set the 5.1-to-2.0 downmix to Lo/Ro.")
_rule("S-515", "SHOULD", f"{DELIVERY}, master",
      "Give every bed channel and object a headphone render mode (Off, Near, Mid or Far).")
_rule("S-516", "shall",
      f"{PROFILE} 2-4",
      "Judge the XML with an ADM profile checker; this release reads the BWF "
      "rules only.")
# -- measured (undetermined in the core) ------------------------------------
_rule("S-520", "MUST", f"{DELIVERY}, loudness (BS.1770-4, tolerance 0.1 LKFS)",
      "Measure the 5.1 loudness re-render, or keep the renderer's loudness report "
      "beside the master.")
_rule("S-521", "MUST",
      f"{DELIVERY}, loudness (tolerance 0.1 dB)",
      "Measure the 5.1 loudness re-render's true peak.")
_rule("S-522", "SHOULD",
      f"{DELIVERY}, master",
      "Low-pass the LFE channel; the specification gives the cut-off range but no slope.")
_rule("S-523", "MUST", f"{DELIVERY}, synchronization",
      "Check against the stereo master: start sample-aligned, end within one frame "
      "(2,000 samples at 48 kHz).")
# -- the album --------------------------------------------------------------
_rule("S-530", "SHOULD",
      f"{DELIVERY}, master",
      "Use the same headphone render mode for each bed channel on every track.")
_rule("S-531", "MUST",
      f"{DELIVERY}, gapless albums",
      "Set the same 5.1-to-2.0 downmix on every track of the gapless album.")
_rule("S-532", "SHOULD",
      f"{DELIVERY}, gapless albums",
      "Use the same 5.1.x downmix and trim settings on every track.")
_rule("S-533", "MUST",
      f"{DELIVERY}, gapless albums",
      "Check every boundary against the stereo album (1,000 samples at 48 kHz).")
_rule("S-534", "SHOULD",
      f"{DELIVERY}, loudness",
      "Measure each track's 5.1 loudness re-render.")

MEASURED = ("S-520", "S-521", "S-522", "S-523")
NOT_MEASURED_WHY = ("needs a measurement of the audio; this release reads the "
                    "file's metadata only")


@dataclass
class Row:
    id: str
    verdict: str
    measured: str
    reference: str
    notes: list[str] = field(default_factory=list)
    basis: str = ""             # set when the reading rests on the dbmd field map

    def to_dict(self) -> dict[str, Any]:
        r = RULES[self.id]
        d: dict[str, Any] = {"id": self.id, "rule": r.title, "level": r.level,
                             "source": r.source, "verdict": self.verdict,
                             "measured": self.measured, "reference": self.reference}
        if self.verdict != PASS:
            d["remedy"] = r.remedy
        if self.notes:
            d["notes"] = list(self.notes)
        if self.basis:
            d["basis"] = self.basis
        return d


def _worst(rows: list[Row]) -> str:
    if any(r.verdict == FAIL for r in rows):
        return FAIL
    if any(r.verdict == WARN for r in rows):
        return WARN
    return PASS


def _counts(rows: list[Row]) -> dict[str, int]:
    c = {PASS: 0, FAIL: 0, WARN: 0, UNDET: 0}
    for r in rows:
        c[r.verdict] += 1
    return c


# --------------------------------------------------------------- one master
def _chunk(info: dict[str, Any], cid: str) -> dict[str, Any] | None:
    for c in info.get("chunks", []):
        if c["id"] == cid:
            return c
    return None


def _riff_bytes(info: dict[str, Any]) -> int:
    ds = info.get("ds64")
    sizes = [info.get("fileSize", 0) - 8]
    if ds and ds.get("riffSize"):
        sizes.append(ds["riffSize"])
    elif info.get("riffSize") not in (None, 0xFFFFFFFF):
        sizes.append(info["riffSize"])
    return max(sizes)


def _track_types(info: dict[str, Any]) -> list[str]:
    """Each audio track's ADM type (the yyyy of AT_yyyyxxxx_nn), in track order.

    BS.2076 puts the typeLabel in the ID: 0001 DirectSpeakers (a bed channel),
    0003 Objects. Sorted by chna's trackIndex, so the n-th entry is the n-th
    audio track, as the dbmd's per-track lists are.
    """
    tracks = sorted((info.get("chna") or {}).get("tracks", []), key=lambda t: t["trackIndex"])
    out = []
    for t in tracks:
        ref = t.get("trackRef") or ""
        out.append(ref[3:7] if ref.startswith("AT_") and len(ref) >= 7 else "?")
    return out


def _mode_counts(modes: list[dict[str, Any]]) -> str:
    order = ["Off", "Near", "Mid", "Far", "not indicated (Mid)"]
    c: dict[str, int] = {}
    for m in modes:
        c[m["name"]] = c.get(m["name"], 0) + 1
    names = order + sorted(k for k in c if k not in order)
    return ", ".join(f"{n} x{c[n]}" for n in names if c.get(n))


def check_master(path: str) -> dict[str, Any]:
    """Every master rule (S-501..S-523) for one file, as a dict."""
    info = adm_info(path)
    rows: list[Row] = []
    facts: dict[str, Any] = {}
    notes: list[str] = []

    # S-501 -- container, chunks, completeness
    ids = [c["id"] for c in info.get("chunks", [])]
    if not info.get("container"):
        rows.append(Row("S-501", FAIL, "not a RIFF/RF64/BW64 WAVE file",
                        "ADM BWF (WAVE with axml and chna)"))
        return _result(path, info, rows, facts, notes, readable=False)
    missing = [c for c in ("fmt ", "chna", "axml", "data") if c not in ids]
    cut = [c for c in info.get("chunks", []) if c.get("truncated")]
    measured = f"{info['container']}/WAVE; " + ("chunks " + ", ".join(i.strip() for i in ids))
    if missing or cut:
        why = []
        if missing:
            why.append("no " + ", ".join(m.strip() for m in missing))
        for c in cut:
            why.append(f"chunk {c['id'].strip()} runs past the end of the file")
        rows.append(Row("S-501", FAIL, measured, "ADM BWF (WAVE with axml and chna)", why))
    else:
        rows.append(Row("S-501", PASS, measured, "ADM BWF (WAVE with axml and chna)"))
    for n in info.get("notes", []):
        notes.append(n)

    fm = info.get("format") or {}
    ch = fm.get("channels")
    rate = fm.get("sampleRate")
    bits = fm.get("bitDepth")
    data = _chunk(info, "data")
    if fm and data and ch and bits and rate:
        frame_bytes = ch * bits // 8
        if frame_bytes:
            facts["durationSeconds"] = round(data["size"] / frame_bytes / rate, 3)
    facts.update({"container": info["container"], "channels": ch, "sampleRate": rate,
                  "bitDepth": bits, "fileSize": info.get("fileSize"),
                  "bext": "bext" in ids})

    # S-502 .. S-506 -- the PCM format
    if not fm:
        for rid in ("S-502", "S-503", "S-505", "S-506"):
            rows.append(Row(rid, FAIL, "no readable fmt chunk", "a PCM fmt chunk"))
    else:
        tag = fm["formatTag"]
        rows.append(Row("S-502", PASS if tag == 1 else FAIL, f"format tag {tag}"
                        + (" (WAVE_FORMAT_EXTENSIBLE)" if tag == 0xFFFE else ""),
                        "1 (PCM)"))
        rows.append(Row("S-503", PASS if 0 < ch <= MAX_CHANNELS else FAIL,
                        f"{ch} channels", f"1 to {MAX_CHANNELS}"))
        rows.append(Row("S-505", PASS if bits == 24 else FAIL, f"{bits}-bit", "24-bit"))
        if rate == 48000:
            rows.append(Row("S-506", PASS, "48000 Hz", "48000 Hz"))
        else:
            n = (["the ADM profile accepts 96 kHz; the delivery specification asks "
                  "for 48 kHz and archives a 96 kHz project as DAMF"]
                 if rate == 96000 else [])
            rows.append(Row("S-506", FAIL, f"{rate} Hz", "48000 Hz", n))

    # S-504 -- track types and the object count (from chna)
    types = _track_types(info)
    beds = sum(1 for t in types if t == "0001")
    objs = sum(1 for t in types if t == "0003")
    other = [t for t in types if t not in ("0001", "0003")]
    facts.update({"bedChannels": beds, "objects": objs})
    if not types:
        rows.append(Row("S-504", UNDET, "no chna tracks to count",
                        f"DirectSpeakers or Objects; at most {MAX_OBJECTS} objects"))
    else:
        bad = []
        if other:
            kinds = sorted({TYPE_NAMES.get(t, f"type {t}") for t in other})
            bad.append(f"{len(other)} track(s) of type {', '.join(kinds)}")
        if objs > MAX_OBJECTS:
            bad.append(f"{objs} objects")
        rows.append(Row("S-504", FAIL if bad else PASS,
                        f"{beds} bed channels + {objs} objects"
                        + (f" + {len(other)} other" if other else ""),
                        f"DirectSpeakers or Objects; at most {MAX_OBJECTS} objects", bad))

    # S-507 / S-509 -- size-dependent container rules
    big = _riff_bytes(info) >= FOUR_GB
    facts["fourGigabytesOrMore"] = big
    cont = info["container"]
    if big:
        rows.append(Row("S-507", PASS if cont == "RF64" else FAIL,
                        f"{cont}, {_riff_bytes(info)} bytes of RIFF data",
                        "RF64 (not BW64, not RIFF)"))
    else:
        rows.append(Row("S-507", PASS, f"{cont}, under 4 GB",
                        "any of RIFF, RF64, BW64 under 4 GB"))
    junk = _chunk(info, "JUNK")
    ds64 = _chunk(info, "ds64")
    over = []
    if not big and junk and junk["size"] > MAX_SMALL_CHUNK:
        over.append(f"JUNK {junk['size']} bytes")
    if big and ds64 and ds64["size"] > MAX_SMALL_CHUNK:
        over.append(f"ds64 {ds64['size']} bytes")
    seen = ([f"JUNK {junk['size']} B"] if junk else []) + ([f"ds64 {ds64['size']} B"] if ds64 else [])
    rows.append(Row("S-509", FAIL if over else PASS, ", ".join(seen) or "neither present",
                    f"at most {MAX_SMALL_CHUNK} bytes"))

    # S-508 -- chna integrity
    chna = info.get("chna")
    if not chna:
        rows.append(Row("S-508", FAIL, "no readable chna", "numUID = numTrack = channels"))
    else:
        bad = []
        if chna["numUIDs"] != chna["numTracks"]:
            bad.append(f"numUID {chna['numUIDs']} != numTrack {chna['numTracks']}")
        if ch is not None and chna["numTracks"] != ch:
            bad.append(f"numTrack {chna['numTracks']} != {ch} channels")
        idx = [t["trackIndex"] for t in chna["tracks"]]
        dup = sorted({i for i in idx if idx.count(i) > 1})
        if dup:
            bad.append("tracks named twice: " + ", ".join(map(str, dup)))
        if ch:
            unnamed = [i for i in range(1, ch + 1) if i not in idx]
            if unnamed:
                bad.append(f"{len(unnamed)} track(s) with no UID (first: {unnamed[0]})")
        if len(chna["tracks"]) < chna["numUIDs"]:
            bad.append(f"chna holds {len(chna['tracks'])} of its {chna['numUIDs']} entries")
        rows.append(Row("S-508", FAIL if bad else PASS,
                        f"numTrack {chna['numTracks']}, numUID {chna['numUIDs']}",
                        "numUID = numTrack = channels, one UID per track", bad))

    # S-510 .. S-515 -- Dolby's block
    d = info.get("dolbyMetadata")
    a = (d or {}).get("atmos") or {}
    s = (d or {}).get("supplemental") or {}
    has9 = "frameRate" in a
    has10 = "binaural" in s
    if d is None:
        rows.append(Row("S-510", WARN, "absent", "present, with segments 9 and 10"))
        why = "no dbmd block: the setting cannot be read"
    elif not d.get("readable", True):
        rows.append(Row("S-510", WARN, f"present, version {d.get('version')}, not readable",
                        "present, with segments 9 and 10", list(d["notes"])))
        why = "the dbmd block could not be read"
    elif not (has9 and has10):
        segs = [x["id"] for x in d["segments"]]
        what = (f"present ({d['size']} bytes), segments {segs}" if segs else
                f"present ({d['size']} bytes) and empty: no segments")
        rows.append(Row("S-510", WARN, what, "present, with segments 9 and 10"))
        why = "the dbmd block carries no Dolby Atmos segment"
    else:
        rows.append(Row("S-510", PASS, f"present ({d['size']} bytes), segments 9 and 10",
                        "present, with segments 9 and 10"))
        why = ""
    caveat = BASIS if (has9 or has10) else ""

    if not has9:
        for rid, ref in (("S-511", "24 fps"), ("S-512", "unassigned"),
                         ("S-513", "Direct Render"), ("S-514", "Lo/Ro")):
            rows.append(Row(rid, UNDET, why or "segment 9 not read", ref))
    else:
        fr = a["frameRate"]
        if fr["code"] == 2:
            rows.append(Row("S-511", PASS, "24 fps", "24 fps", basis=caveat))
        elif fr["code"] == 0:
            rows.append(Row("S-511", UNDET, "not indicated", "24 fps", basis=caveat))
        else:
            rows.append(Row("S-511", FAIL, f"{fr['name']} fps", "24 fps", basis=caveat))
        ff = a["firstFrameOfAction"]
        if ff is None:
            rows.append(Row("S-512", PASS, "unassigned", "unassigned", basis=caveat))
        else:
            rows.append(Row("S-512", FAIL, f"set at {ff['seconds']:.5f} s", "unassigned",
                            basis=caveat))
        w = a["downmix5_1x"]
        rows.append(Row("S-513", PASS if w["code"] == 0 else WARN, w["name"],
                        "Direct Render", basis=caveat))
        dm = a["downmix5to2"]
        n = []
        if dm["code"] == 0:
            n.append("the setting is not indicated; readers take it as Lo/Ro, "
                     "but the specification asks for it to be set")
        rows.append(Row("S-514", PASS if dm["code"] == 1 else WARN, dm["name"], "Lo/Ro", n,
                        basis=caveat))

    if not has10:
        rows.append(Row("S-515", UNDET, why or "segment 10 not read",
                        "a mode on every bed channel and object"))
    else:
        modes = s["binaural"]
        bad = []
        unset = [m for m in modes if m["code"] >= 4]
        if unset:
            bad.append(f"{len(unset)} track(s) not indicated (first: track "
                       f"{unset[0]['index'] + 1})")
        if ch and len(modes) < ch:
            bad.append(f"segment 10 gives modes for {len(modes)} of {ch} tracks")
        n = list(bad)
        if modes and all(m["code"] == 0 for m in modes):
            n.append("every track is Off")
        rows.append(Row("S-515", WARN if bad else PASS, _mode_counts(modes) or "no tracks",
                        "a mode on every bed channel and object", n, basis=caveat))
        facts["binaural"] = [m["name"] for m in modes]

    rows.append(Row("S-516", UNDET, f"axml {(_chunk(info, 'axml') or {}).get('size', 0)} bytes, "
                    "not judged", "the profile's XML rules (sections 2-4)"))

    for rid, ref in (("S-520", "at most -18.0 LKFS"), ("S-521", "at most -1.0 dBTP"),
                     ("S-522", "cut-off 100-150 Hz"),
                     ("S-523", "no extra lead silence; tail < 1 frame")):
        why2 = (NOT_MEASURED_WHY if rid != "S-523" else
                "needs the stereo master beside this one")
        rows.append(Row(rid, UNDET, "not measured", ref, [why2]))

    if caveat:
        notes.append("S-511..S-515 read Dolby's block: " + caveat)
    if a or s:
        facts["dolby"] = {
            "frameRate": a.get("frameRate", {}).get("name"),
            "firstFrameOfAction": (None if not a or a.get("firstFrameOfAction") is None
                                   else a["firstFrameOfAction"]["seconds"]),
            "downmix5to2": a.get("downmix5to2", {}).get("code"),
            "downmix5_1x": a.get("downmix5_1x", {}).get("code"),
            "trims": s.get("trims"),
            "writtenBy": (f"{a.get('contentCreationTool') or '(blank)'} "
                          f"{a.get('contentCreationToolVersion', '')}".strip() if a else None),
        }
    return _result(path, info, rows, facts, notes, readable=True)


def _result(path, info, rows, facts, notes, *, readable):
    order = {rid: i for i, rid in enumerate(RULES)}
    rows.sort(key=lambda r: order[r.id])
    verdict = _worst(rows)
    counts = _counts(rows)
    return {"path": path, "readable": readable, "isAdm": bool(info.get("isAdm")),
            "verdict": verdict, "complete": counts[UNDET] == 0, "counts": counts,
            "facts": facts,
            "rows": [r.to_dict() for r in rows], "notes": notes,
            "_bed_types": _track_types(info) if readable else []}


# ---------------------------------------------------------------- the album
def check_album(name: str, masters: list[dict[str, Any]], gapless: bool) -> dict[str, Any]:
    rows: list[Row] = []
    usable = [m for m in masters if m["readable"]]
    # S-530: bed channels' headphone modes, position by position
    beds = []
    for m in usable:
        modes = m["facts"].get("binaural")
        types = m.get("_bed_types") or []
        if modes is None:
            beds.append(None)
            continue
        beds.append(tuple(md for md, t in zip(modes, types) if t == "0001"))
    known = [b for b in beds if b is not None]
    if len(known) < 2:
        rows.append(Row("S-530", UNDET, f"modes read on {len(known)} of {len(usable)} tracks",
                        "the same mode for each bed channel on every track"))
    else:
        ref = known[0]
        diff = [os.path.basename(m["path"]) for m, b in zip(usable, beds)
                if b is not None and b != ref]
        n = [] if len(known) == len(usable) else [
            f"{len(usable) - len(known)} track(s) carry no modes and were not compared"]
        n.append("bed channels compared position by position; objects differ by "
                 "song and are not compared")
        rows.append(Row("S-530", WARN if diff else PASS,
                        ("differs on " + ", ".join(diff)) if diff else
                        f"bed modes identical on {len(known)} tracks",
                        "the same mode for each bed channel on every track", n))
    if gapless:
        def field_of(m, key):
            dd = m["facts"].get("dolby") or {}
            return dd.get(key) if "frameRate" in dd and dd["frameRate"] is not None else None
        vals = [field_of(m, "downmix5to2") for m in usable]
        if any(v is None for v in vals) or not vals:
            rows.append(Row("S-531", UNDET, "the setting is unreadable on "
                            f"{sum(v is None for v in vals)} track(s)",
                            "identical on every track"))
        else:
            rows.append(Row("S-531", PASS if len(set(vals)) == 1 else FAIL,
                            f"{len(set(vals))} distinct setting(s) over {len(vals)} tracks",
                            "identical on every track"))
        pairs = [(field_of(m, "downmix5_1x"), json.dumps((m["facts"].get("dolby") or {})
                                                         .get("trims"), sort_keys=True))
                 for m in usable]
        if any(p[0] is None for p in pairs) or not pairs:
            rows.append(Row("S-532", UNDET, "unreadable on "
                            f"{sum(p[0] is None for p in pairs)} track(s)",
                            "identical on every track"))
        else:
            rows.append(Row("S-532", PASS if len(set(pairs)) == 1 else WARN,
                            f"{len(set(pairs))} distinct combination(s) over {len(pairs)} tracks",
                            "identical on every track"))
        rows.append(Row("S-533", UNDET, "not measured", "within 1,000 samples at 48 kHz",
                        ["needs the stereo album beside these masters"]))
    rows.append(Row("S-534", UNDET, "not measured", "at most -18.0 LKFS",
                    [NOT_MEASURED_WHY]))
    counts = _counts(rows)
    return {"album": name, "tracks": [m["path"] for m in masters], "gapless": gapless,
            "verdict": _worst(rows), "complete": counts[UNDET] == 0, "counts": counts,
            "rows": [r.to_dict() for r in rows]}


# ------------------------------------------------------------ files, folders
def _is_master_name(name: str) -> bool:
    return name.lower().endswith(MASTER_EXTS) and not name.startswith("._")


def collect(paths: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(masters to check, files skipped as not ADM, paths that do not exist)."""
    files: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for dirpath, dirs, names in os.walk(p):
                dirs.sort()
                for nm in sorted(names):
                    if not _is_master_name(nm):
                        continue
                    full = os.path.join(dirpath, nm)
                    try:
                        info = adm_info(full)
                    except OSError:
                        skipped.append(full)
                        continue
                    (files if info.get("isAdm") else skipped).append(full)
        else:
            missing.append(p)
    return files, skipped, missing


def run(paths: list[str], *, album: bool = False, gapless: bool = False,
        strict: bool = False) -> dict[str, Any]:
    files, skipped, missing = collect(paths)
    masters = []
    errors = [f"{p}: no such file or folder" for p in missing]
    if not files and not missing:
        errors.append("no ADM master (a WAVE file with axml and chna) found in "
                      + ", ".join(paths))
    for f in files:
        try:
            masters.append(check_master(f))
        except OSError as e:
            errors.append(f"{f}: {e}")
    albums = []
    if album or gapless:
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in masters:
            groups.setdefault(os.path.dirname(os.path.abspath(m["path"])), []).append(m)
        for name, ms in sorted(groups.items()):
            albums.append(check_album(name, ms, gapless))
    for m in masters:
        m.pop("_bed_types", None)
    fail_at = WARN if strict else FAIL
    worst = max([_RANK[m["verdict"]] for m in masters] +
                [_RANK[a["verdict"]] for a in albums] + [0])
    exit_code = 2 if errors or any(not m["readable"] for m in masters) or not masters else (
        1 if worst >= _RANK[fail_at] else 0)
    totals = {PASS: 0, FAIL: 0, WARN: 0, UNDET: 0}
    for x in masters + albums:
        for k, v in x["counts"].items():
            totals[k] += v
    return {"tool": "sentinel adm-check", "specifications": [DELIVERY, PROFILE],
            "masters": masters, "albums": albums, "skipped": skipped, "errors": errors,
            "totals": totals, "strict": strict, "exit_code": exit_code,
            "disclaimer": ("Built on Dolby's public specifications; not affiliated with "
                           "or endorsed by Dolby Laboratories. A PASS is not Dolby "
                           "certification; UNDETERMINED rules were not judged.")}


# ----------------------------------------------------------------- renderers
_LABEL = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", UNDET: "UNDETERMINED"}


def _verdict_line(x: dict[str, Any]) -> str:
    """The headline. "PASSES" only when every rule was judged; a master with
    rules left undetermined has had nothing fail, which is a different claim."""
    c = x["counts"]
    if x["verdict"] == FAIL:
        head = "FAILS"
    elif c[UNDET]:
        head = "NOTHING FAILED" + (f", {c[WARN]} WARNING(S)" if c[WARN] else "") + \
            f"; {c[UNDET]} RULE(S) NOT DETERMINED"
    else:
        head = "PASSES WITH WARNINGS" if c[WARN] else "PASSES"
    return (f"{head}  ({c[FAIL]} fail, {c[WARN]} warn, {c[PASS]} pass, "
            f"{c[UNDET]} not determined)")


def _summary(m: dict[str, Any]) -> str:
    f = m["facts"]
    if not m["readable"]:
        return "not a WAVE file"
    bits = []
    if f.get("channels") is not None:
        bits.append(f"{f['channels']} ch ({f.get('bedChannels', 0)} bed + "
                    f"{f.get('objects', 0)} objects)")
    if f.get("sampleRate"):
        bits.append(f"{f['sampleRate'] / 1000:g} kHz / {f.get('bitDepth')}-bit")
    if f.get("durationSeconds") is not None:
        mm, ss = divmod(f["durationSeconds"], 60)
        bits.append(f"{int(mm)}:{ss:06.3f}")
    bits.append(f["container"])
    if (f.get("dolby") or {}).get("writtenBy"):
        bits.append(f"dbmd written by {f['dolby']['writtenBy']}")
    return " · ".join(bits)


def render_text(res: dict[str, Any]) -> str:
    L = [f"Sentinel adm-check — {DELIVERY}; {PROFILE}"]
    for m in res["masters"]:
        L += ["", m["path"], f"  {_summary(m)}", f"  {_verdict_line(m)}"]
        for r in m["rows"]:
            L.append(f"  {_LABEL[r['verdict']]:<12} {r['id']}  {r['rule']}")
            L.append(f"  {'':<12}        measured: {r['measured']}  |  required: {r['reference']}"
                     f"  [{r['level']}]")
            for n in r.get("notes", []):
                L.append(f"  {'':<12}        note: {n}")
            if r["verdict"] in (FAIL, WARN):
                L.append(f"  {'':<12}        to fix: {r['remedy']}")
        for n in m["notes"]:
            L.append(f"  note: {n}")
    for a in res["albums"]:
        L += ["", f"Album: {a['album']}  ({len(a['tracks'])} tracks"
              + (", gapless" if a["gapless"] else "") + ")", f"  {_verdict_line(a)}"]
        for r in a["rows"]:
            L.append(f"  {_LABEL[r['verdict']]:<12} {r['id']}  {r['rule']}: {r['measured']}")
            for n in r.get("notes", []):
                L.append(f"  {'':<12}        note: {n}")
    if res["skipped"]:
        L += ["", f"Skipped {len(res['skipped'])} file(s) with no axml/chna (not ADM masters):"]
        L += [f"  {p}" for p in res["skipped"]]
    for e in res["errors"]:
        L += [f"error: {e}"]
    t = res["totals"]
    L += ["", f"{len(res['masters'])} master(s), {len(res['albums'])} album(s): "
          f"{t[FAIL]} fail, {t[WARN]} warn, {t[PASS]} pass, {t[UNDET]} not determined; "
          f"exit {res['exit_code']}", res["disclaimer"]]
    return "\n".join(L)


def render_json(res: dict[str, Any]) -> str:
    return json.dumps(res, indent=2)


_CSS = """
body{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:1.5rem;color:#1b1f24;background:#fff}
h1{font-size:1.15rem;margin:0 0 .2rem} h2{font-size:1rem;margin:1.6rem 0 .2rem;word-break:break-all}
.sub,.foot,.note{color:#57606a} .sub{margin:.1rem 0 .5rem} .foot{margin-top:1.5rem;font-size:.78rem}
table{border-collapse:collapse;width:100%;margin-top:.4rem} th,td{border-bottom:1px solid #d0d7de;
padding:.3rem .45rem;text-align:left;vertical-align:top} th{background:#f6f8fa;font-size:.7rem;
text-transform:uppercase;letter-spacing:.04em;color:#57606a}
.v{color:#fff;padding:.05rem .4rem;border-radius:.25rem;font-size:.7rem;font-weight:700;white-space:nowrap}
.PASS{background:#1a7f37}.FAIL{background:#cf222e}.WARN{background:#9a6700}.UNDETERMINED{background:#6e7781}
.badge{display:inline-block;color:#fff;padding:.12rem .55rem;border-radius:.35rem;font-weight:600}
.id{font-family:ui-monospace,Menlo,monospace;color:#57606a;white-space:nowrap} .note{font-size:.78rem}
@media print{body{margin:.6cm} h2{page-break-before:auto}}
"""


def render_html(res: dict[str, Any]) -> str:
    e = html.escape
    out = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
           "<title>ADM delivery check</title><style>", _CSS, "</style></head><body>",
           "<h1>ADM master delivery check</h1>",
           f"<div class=\"sub\">Judged against the {e(DELIVERY)} and the {e(PROFILE)}.</div>"]

    def table(rows):
        fixing = any(r["verdict"] in (FAIL, WARN) for r in rows)
        b = ["<table><tr><th>Verdict</th><th>Rule</th><th>Measured</th><th>Required</th>"
             + ("<th>To fix</th>" if fixing else "") + "</tr>"]
        for r in rows:
            notes = "".join(f"<div class=\"note\">{e(n)}</div>" for n in r.get("notes", []))
            fix = e(r["remedy"]) if r["verdict"] in (FAIL, WARN) else ""
            b.append(f"<tr><td><span class=\"v {r['verdict']}\">{_LABEL[r['verdict']]}</span></td>"
                     f"<td><span class=\"id\">{r['id']}</span> {e(r['rule'])}"
                     f"<div class=\"note\">{e(r['level'])} · {e(r['source'])}</div></td>"
                     f"<td>{e(r['measured'])}{notes}</td><td>{e(r['reference'])}</td>"
                     + (f"<td>{fix}</td>" if fixing else "") + "</tr>")
        b.append("</table>")
        return "".join(b)

    colour = {FAIL: "#cf222e", WARN: "#9a6700", PASS: "#1a7f37"}
    for m in res["masters"]:
        out.append(f"<h2>{e(os.path.basename(m['path']))}</h2>")
        out.append(f"<div class=\"sub\">{e(_summary(m))}</div>")
        out.append(f"<span class=\"badge\" style=\"background:{colour[m['verdict']]}\">"
                   f"{e(_verdict_line(m))}</span>")
        out.append(table(m["rows"]))
        for n in m["notes"]:
            out.append(f"<div class=\"note\">{e(n)}</div>")
    for a in res["albums"]:
        out.append(f"<h2>Album: {e(a['album'])}</h2>")
        out.append(f"<div class=\"sub\">{len(a['tracks'])} tracks"
                   + (", gapless" if a["gapless"] else "") + "</div>")
        out.append(f"<span class=\"badge\" style=\"background:{colour[a['verdict']]}\">"
                   f"{e(_verdict_line(a))}</span>")
        out.append(table(a["rows"]))
    if res["skipped"]:
        out.append("<div class=\"foot\">Skipped (no axml/chna): "
                   + ", ".join(e(os.path.basename(p)) for p in res["skipped"]) + "</div>")
    for err in res["errors"]:
        out.append(f"<div class=\"foot\">error: {e(err)}</div>")
    out.append(f"<div class=\"foot\">{e(res['disclaimer'])} Dolby-block readings follow a "
               f"third-party field map: {e(BASIS)}.</div></body></html>")
    return "".join(out)


def render(res: dict[str, Any], fmt: str) -> str:
    return {"json": render_json, "html": render_html}.get(fmt, render_text)(res)
