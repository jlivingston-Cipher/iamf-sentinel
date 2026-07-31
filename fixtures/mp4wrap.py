"""Minimal IAMF-in-MP4 wrapper for container-check fixtures.

Clean-room, written from ISO/IEC 14496-12 box structure + the IAMF ISOBMFF
encapsulation — just enough box structure for Sentinel's walker (parse_mp4 /
extract_iamf_stream): ftyp, moov/trak/[edts/elst]/mdia(mdhd, hdlr,
minf/stbl(stsd(iamf/iacb), stts, stsz, stsc, stco)), mdat. One MP4 sample per
temporal unit; descriptors ride in iacb.

Used by the S-407/S-408/S-409 trim-carriage fixtures (F31): the wrapper lets a
test place the edit list and sample table in or out of agreement with the OBU
trimming fields, byte-for-byte deterministically.
"""

from __future__ import annotations


def _box(fourcc: str, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + fourcc.encode("latin-1") + payload


def _full(fourcc: str, version: int, flags: int, payload: bytes) -> bytes:
    return _box(fourcc, bytes([version]) + flags.to_bytes(3, "big") + payload)


def _uleb(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _read_uleb(data: bytes, p: int) -> tuple[int, int]:
    v = shift = 0
    while True:
        b = data[p]
        p += 1
        v |= (b & 0x7F) << shift
        if not (b & 0x80):
            return v, p
        shift += 7


def split_stream(data: bytes) -> tuple[bytes, list[bytes]]:
    """Split a raw IA stream into (descriptor_obus, [one bytes-chunk per TU]).

    TU boundary rule: a new temporal unit starts at a temporal-delimiter OBU,
    or when an audio frame repeats a substream id already seen in the current
    unit (fixture streams carry one frame per substream per TU).
    """
    p, n = 0, len(data)
    desc_end = None
    tu_bounds: list[int] = []
    seen: set[int] = set()
    while p + 2 <= n:
        b0 = data[p]
        obu_type = b0 >> 3
        trimming = (b0 >> 1) & 1
        extension = b0 & 1
        size, q = _read_uleb(data, p + 1)
        body_start = q
        if q + size > n:
            break
        if 5 <= obu_type <= 23 or obu_type == 4:
            if desc_end is None:
                desc_end = p
            if obu_type == 4:                      # temporal delimiter
                tu_bounds.append(p)
                seen = set()
            else:
                fp = body_start
                if trimming:
                    _, fp = _read_uleb(data, fp)   # trim_at_end
                    _, fp = _read_uleb(data, fp)   # trim_at_start
                if extension:
                    ext, fp = _read_uleb(data, fp)
                    fp += ext
                sid = obu_type - 6 if obu_type >= 6 else _read_uleb(data, fp)[0]
                if sid in seen:
                    tu_bounds.append(p)
                    seen = set()
                elif not seen and not tu_bounds:
                    tu_bounds.append(p)
                seen.add(sid)
        p = q + size
    if desc_end is None:
        return data, []
    tu_bounds.append(p)
    chunks = [data[tu_bounds[i]:tu_bounds[i + 1]] for i in range(len(tu_bounds) - 1)]
    return data[:desc_end], chunks


def wrap_mp4(iamf: bytes, *, timescale: int = 48000, sample_duration: int = 480,
             elst: list[tuple[int, int]] | None = None, edts_no_elst: bool = False,
             stts: list[tuple[int, int]] | None = None,
             brands: tuple[str, ...] = ("iamf", "isom")) -> bytes:
    """Wrap a raw IA stream in a minimal MP4.

    elst: list of (segment_duration, media_time) version-0 entries (rate 1.0);
    None = no edts at all. stts: (count, delta) override; default = uniform
    sample_duration per TU.
    """
    desc, tus = split_stream(iamf)
    n = len(tus)
    stts_entries = stts if stts is not None else [(n, sample_duration)]
    media_duration = sum(c * d for c, d in stts_entries)

    ftyp = _box("ftyp", b"iamf" + (0).to_bytes(4, "big")
                + b"".join(b.encode("latin-1") for b in brands))

    iacb = _box("iacb", bytes([1]) + _uleb(len(desc)) + desc)
    entry = _box("iamf", bytes(6) + (1).to_bytes(2, "big")     # SampleEntry
                 + bytes(8)                                     # reserved
                 + (2).to_bytes(2, "big") + (16).to_bytes(2, "big")  # ch, bits
                 + bytes(4) + (timescale << 16).to_bytes(4, "big")   # rate 16.16
                 + iacb)
    stsd = _full("stsd", 0, 0, (1).to_bytes(4, "big") + entry)
    stts_b = _full("stts", 0, 0, len(stts_entries).to_bytes(4, "big")
                   + b"".join(c.to_bytes(4, "big") + d.to_bytes(4, "big")
                              for c, d in stts_entries))
    stsz = _full("stsz", 0, 0, (0).to_bytes(4, "big") + n.to_bytes(4, "big")
                 + b"".join(len(t).to_bytes(4, "big") for t in tus))
    stsc = _full("stsc", 0, 0, (1).to_bytes(4, "big")
                 + (1).to_bytes(4, "big") + n.to_bytes(4, "big")
                 + (1).to_bytes(4, "big"))
    stco_payload_prefix = (1).to_bytes(4, "big")

    mdhd = _full("mdhd", 0, 0, bytes(8) + timescale.to_bytes(4, "big")
                 + media_duration.to_bytes(4, "big")
                 + (0x55C4).to_bytes(2, "big") + bytes(2))
    hdlr = _full("hdlr", 0, 0, bytes(4) + b"soun" + bytes(12) + b"IAMF\x00")

    def moov_bytes(chunk_offset: int) -> bytes:
        stco = _full("stco", 0, 0, stco_payload_prefix
                     + chunk_offset.to_bytes(4, "big"))
        stbl = _box("stbl", stsd + stts_b + stsz + stsc + stco)
        minf = _box("minf", stbl)
        mdia = _box("mdia", mdhd + hdlr + minf)
        edts = b""
        if edts_no_elst:
            edts = _box("edts", b"")
        elif elst is not None:
            payload = len(elst).to_bytes(4, "big") + b"".join(
                seg.to_bytes(4, "big")
                + mt.to_bytes(4, "big", signed=True)
                + (1).to_bytes(2, "big") + bytes(2)
                for seg, mt in elst)
            edts = _box("edts", _full("elst", 0, 0, payload))
        trak = _box("trak", edts + mdia)
        return _box("moov", trak)

    moov = moov_bytes(0)
    mdat_payload = b"".join(tus)
    chunk_offset = len(ftyp) + len(moov) + 8       # mdat payload start
    moov = moov_bytes(chunk_offset)
    return ftyp + moov + _box("mdat", mdat_payload)
