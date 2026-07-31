"""Minimal ISO-BMFF box walker for IAMF-in-MP4 (Sentinel container layer, R4).

Clean-room, written from ISO/IEC 14496-12 + the IAMF ISOBMFF encapsulation.
Only what the container checks need: ftyp brand set, box ordering (fast-start),
the 'iamf' sample entry, and the IAConfigurationBox ('iacb') descriptor OBUs so
L1/L2 run on MP4-embedded descriptors exactly as they do on raw .iamf.
"""

from __future__ import annotations
from collections.abc import Iterator
from dataclasses import dataclass, field

# Robustness cap (item 22, doc 84): sample-table counts are attacker-controlled
# 32-bit fields. Loops that read per-entry bytes self-bound on buffer overrun,
# but a constant-size `stsz` declares its count with no backing bytes to run
# out of — `[size] * count` materializes a multi-billion-element list on a
# smashed count (a fuzz-found DoS: no crash, just an unbounded allocation that
# never returns). A real constant-size sample occupies >= 1 mdat byte, so a
# legitimate count can never exceed the file length; clamp to it (under a
# generous absolute ceiling) so the walk degrades to a structured finding
# instead of hanging, without ever clamping a real file's sample table.
_MAX_TABLE_ENTRIES = 8_000_000


@dataclass
class TrackInfo:
    handler: str = ""
    timescale: int | None = None
    duration: int | None = None
    stts: list[tuple[int, int]] = field(default_factory=list)   # (count, delta)
    ctts_present: bool = False
    has_iamf: bool = False
    sample_sizes: list[int] = field(default_factory=list)        # stsz
    chunk_offsets: list[int] = field(default_factory=list)       # stco/co64
    stsc: list[tuple[int, int]] = field(default_factory=list)    # (first_chunk, per_chunk)
    # Edit list (ISO/IEC 14496-12 §8.6.5/§8.6.6) — normative for IAMF trimming
    # (IAMF v1.1.0 §6.2.2 SHALL). F31: FFmpeg strips trim and writes media_time=0.
    edts_present: bool = False
    elst_entries: list[tuple[int, int, int]] = field(default_factory=list)
    # (segment_duration, media_time, media_rate_integer); media_time signed

    @property
    def duration_s(self) -> float | None:
        if self.timescale and self.duration is not None:
            return self.duration / self.timescale
        return None


@dataclass
class MP4Info:
    major_brand: str = ""
    minor_version: int = 0
    compatible_brands: list[str] = field(default_factory=list)
    top_level_order: list[str] = field(default_factory=list)
    has_iamf_sample_entry: bool = False
    descriptor_obus: bytes = b""
    video_present: bool = False
    tracks: list[TrackInfo] = field(default_factory=list)
    # Audio-frame refs (with trimming fields) re-walked from the reconstructed
    # IA stream; populated by the engine so the trim checks (S-407..S-409) can
    # see MP4-carried frames. Empty when reconstruction is not possible.
    frame_refs: list = field(default_factory=list)


def _read_boxes(data: bytes, start: int,
                end: int) -> Iterator[tuple[str, int, int, int]]:
    """Yield (fourcc, box_start, payload_start, box_end) for boxes in [start,end)."""
    p = start
    while p + 8 <= end:
        size = int.from_bytes(data[p:p + 4], "big")
        fourcc = data[p + 4:p + 8].decode("latin-1", "replace")
        header = 8
        if size == 1:
            if p + 16 > end:
                break
            size = int.from_bytes(data[p + 8:p + 16], "big")
            header = 16
        elif size == 0:
            size = end - p
        if size < header or p + size > end:
            break
        yield fourcc, p, p + header, p + size
        p += size


def parse_mp4(data: bytes) -> MP4Info:
    info = MP4Info()
    for fourcc, bstart, pstart, bend in _read_boxes(data, 0, len(data)):
        info.top_level_order.append(fourcc)
        if fourcc == "ftyp":
            info.major_brand = data[pstart:pstart + 4].decode("latin-1", "replace")
            info.minor_version = int.from_bytes(data[pstart + 4:pstart + 8], "big")
            q = pstart + 8
            while q + 4 <= bend:
                info.compatible_brands.append(data[q:q + 4].decode("latin-1", "replace"))
                q += 4
        elif fourcc == "moov":
            _walk_moov(data, pstart, bend, info)
    return info


def _walk_moov(data: bytes, start: int, end: int, info: MP4Info) -> None:
    for fourcc, bstart, pstart, bend in _read_boxes(data, start, end):
        if fourcc == "trak":
            _walk_trak(data, pstart, bend, info)


def _parse_elst(data: bytes, start: int, end: int, track: TrackInfo) -> None:
    """trak -> edts -> elst (ISO/IEC 14496-12 §8.6.6). Version 0 and 1."""
    track.edts_present = True
    for fc, _bs, ps, be in _read_boxes(data, start, end):
        if fc != "elst":
            continue
        ver = data[ps]
        n = int.from_bytes(data[ps + 4:ps + 8], "big")
        q = ps + 8
        for _ in range(min(n, 10000)):
            if ver == 1:
                if q + 20 > be:
                    break
                seg = int.from_bytes(data[q:q + 8], "big")
                mt = int.from_bytes(data[q + 8:q + 16], "big", signed=True)
                rate = int.from_bytes(data[q + 16:q + 18], "big", signed=True)
                q += 20
            else:
                if q + 12 > be:
                    break
                seg = int.from_bytes(data[q:q + 4], "big")
                mt = int.from_bytes(data[q + 4:q + 8], "big", signed=True)
                rate = int.from_bytes(data[q + 8:q + 10], "big", signed=True)
                q += 12
            track.elst_entries.append((seg, mt, rate))


def _walk_trak(data: bytes, start: int, end: int, info: MP4Info) -> None:
    track = TrackInfo()
    for fourcc, bstart, pstart, bend in _read_boxes(data, start, end):
        if fourcc == "edts":
            _parse_elst(data, pstart, bend, track)
        elif fourcc == "mdia":
            _walk_container(data, pstart, bend, info, ["minf", "stbl", "stsd"])
            _collect_timing(data, pstart, bend, track)
            for fc, _bs, ps, be in _read_boxes(data, pstart, bend):
                if fc == "hdlr":
                    handler = data[ps + 8:ps + 12].decode("latin-1", "replace")
                    track.handler = handler
                    if handler == "vide":
                        info.video_present = True
                if fc == "mdhd":
                    ver = data[ps]
                    if ver == 0:
                        track.timescale = int.from_bytes(data[ps + 12:ps + 16], "big")
                        track.duration = int.from_bytes(data[ps + 16:ps + 20], "big")
                    elif ver == 1:
                        track.timescale = int.from_bytes(data[ps + 20:ps + 24], "big")
                        track.duration = int.from_bytes(data[ps + 24:ps + 32], "big")
    info.tracks.append(track)


def _collect_timing(data: bytes, start: int, end: int,
                    track: TrackInfo) -> None:
    """mdia -> minf -> stbl -> {stts, ctts, stsd, stsz, stco/co64, stsc}."""
    for fc, _bs, ps, be in _read_boxes(data, start, end):
        if fc == "minf":
            for fc2, _bs2, ps2, be2 in _read_boxes(data, ps, be):
                if fc2 == "stbl":
                    for fc3, _bs3, ps3, be3 in _read_boxes(data, ps2, be2):
                        if fc3 == "stts":
                            n = int.from_bytes(data[ps3 + 4:ps3 + 8], "big")
                            q = ps3 + 8
                            for _ in range(min(n, 10000)):
                                if q + 8 > be3:
                                    break
                                cnt = int.from_bytes(data[q:q + 4], "big")
                                delta = int.from_bytes(data[q + 4:q + 8], "big")
                                track.stts.append((cnt, delta))
                                q += 8
                        elif fc3 == "ctts":
                            track.ctts_present = True
                        elif fc3 == "stsd":
                            for sfc, _s1, _s2, _s3 in _read_boxes(data, ps3 + 8, be3):
                                if sfc == "iamf":
                                    track.has_iamf = True
                        elif fc3 == "stsz":
                            size = int.from_bytes(data[ps3 + 4:ps3 + 8], "big")
                            n = int.from_bytes(data[ps3 + 8:ps3 + 12], "big")
                            if size:
                                # constant size: `n` has no backing bytes to
                                # bound it — a smashed count would allocate an
                                # arbitrarily large list. A real sample is
                                # >= 1 byte, so n <= len(data) always (item 22).
                                n = min(n, len(data), _MAX_TABLE_ENTRIES)
                                track.sample_sizes = [size] * n
                            else:
                                q = ps3 + 12
                                for _ in range(n):
                                    if q + 4 > be3:
                                        break
                                    track.sample_sizes.append(
                                        int.from_bytes(data[q:q + 4], "big"))
                                    q += 4
                        elif fc3 in ("stco", "co64"):
                            w = 4 if fc3 == "stco" else 8
                            n = int.from_bytes(data[ps3 + 4:ps3 + 8], "big")
                            q = ps3 + 8
                            for _ in range(n):
                                if q + w > be3:
                                    break
                                track.chunk_offsets.append(
                                    int.from_bytes(data[q:q + w], "big"))
                                q += w
                        elif fc3 == "stsc":
                            n = int.from_bytes(data[ps3 + 4:ps3 + 8], "big")
                            q = ps3 + 8
                            for _ in range(n):
                                if q + 12 > be3:
                                    break
                                first = int.from_bytes(data[q:q + 4], "big")
                                per = int.from_bytes(data[q + 4:q + 8], "big")
                                track.stsc.append((first, per))
                                q += 12


def extract_iamf_stream(data: bytes, info: MP4Info) -> bytes | None:
    """Reconstruct a raw .iamf byte stream from an IAMF-in-MP4 file.

    Clean-room, per the IAMF ISOBMFF encapsulation: the iacb box carries the
    descriptor OBUs; each MP4 sample of the 'iamf' track carries one temporal
    unit's OBUs. Concatenating descriptors + samples in order yields a valid
    raw IA sequence — which lets the reference-decoder oracles (raw-input
    only, or crash-prone on A/V MP4) run on exactly the delivered audio.
    """
    if not info.descriptor_obus:
        return None
    track = next((t for t in info.tracks if t.has_iamf), None)
    if track is None or not track.sample_sizes or not track.chunk_offsets:
        return None
    # expand stsc runs -> samples per chunk
    per_chunk: list[int] = []
    stsc = track.stsc or [(1, len(track.sample_sizes))]
    for i, (first, per) in enumerate(stsc):
        last = stsc[i + 1][0] - 1 if i + 1 < len(stsc) else len(track.chunk_offsets)
        per_chunk += [per] * max(0, last - first + 1)
    out = [info.descriptor_obus]
    si = 0
    for ci, coff in enumerate(track.chunk_offsets):
        n = per_chunk[ci] if ci < len(per_chunk) else 0
        off = coff
        for _ in range(n):
            if si >= len(track.sample_sizes):
                break
            size = track.sample_sizes[si]
            if off + size > len(data):
                return None                      # corrupt tables — bail cleanly
            out.append(data[off:off + size])
            off += size
            si += 1
    if si != len(track.sample_sizes):
        return None
    return b"".join(out)


def _walk_container(data: bytes, start: int, end: int, info: MP4Info,
                    path: str) -> None:
    """Descend a fixed child-box path, then process the terminal (stsd)."""
    target = path[0]
    for fourcc, bstart, pstart, bend in _read_boxes(data, start, end):
        if fourcc == target:
            if len(path) == 1:
                _walk_stsd(data, pstart, bend, info)
            else:
                _walk_container(data, pstart, bend, info, path[1:])


def _walk_stsd(data: bytes, start: int, end: int, info: MP4Info) -> None:
    # stsd: FullBox(4) + entry_count(4) then sample entries
    p = start + 8
    for fourcc, bstart, pstart, bend in _read_boxes(data, p, end):
        if fourcc == "iamf":
            info.has_iamf_sample_entry = True
            # AudioSampleEntry fixed part = 8 (SampleEntry) + 20 (audio) = 28 bytes
            child = pstart + 28
            for cfc, cbs, cps, cbe in _read_boxes(data, child, bend):
                if cfc == "iacb":
                    info.descriptor_obus = _extract_iacb_descriptors(data[cps:cbe])


def _extract_iacb_descriptors(payload: bytes) -> bytes:
    """Return the descriptor OBU bytes from an IAConfigurationBox payload.

    Robust to the small iacb prefix (configurationVersion / size fields): locate
    the IA Sequence Header OBU, which is byte 0xF8 followed by a leb128 size and
    the 'iamf' 4CC, and return from there to the end of the box.
    """
    idx = payload.find(b"iamf")
    while idx != -1:
        # sequence header OBU: 0xF8, <leb128 size>, 'iamf'. size is one byte here (6).
        if idx >= 2 and payload[idx - 2] == 0xF8:
            return payload[idx - 2:]
        idx = payload.find(b"iamf", idx + 1)
    return b""
