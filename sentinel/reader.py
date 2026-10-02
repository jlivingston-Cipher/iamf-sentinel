"""Bounds-checked byte reader for the IAMF OBU bitstream.

Clean-room implementation written from the AOM IAMF v1.1.0 specification
(OBU syntax, leb128, ISO-BMFF only). No code is derived from any reference
decoder or encoder (project ADR-3). Every out-of-bounds access raises
``ParseError`` rather than crashing, so malformed/truncated input yields a
structured L1 finding (PRD R1 accept criterion: "fuzzed/truncated inputs
never crash").
"""

from __future__ import annotations


class ParseError(Exception):
    """Raised on any malformed/out-of-bounds read. Carries a byte offset."""

    def __init__(self, message: str, offset: int | None = None) -> None:
        self.offset = offset
        super().__init__(message if offset is None else f"{message} (at byte {offset})")


class ByteReader:
    """Sequential big-endian reader over a bytes buffer with hard bounds."""

    def __init__(self, data: bytes, base: int = 0) -> None:
        self._d = data
        self._p = 0
        self._base = base  # absolute offset of byte 0, for diagnostics

    # -- position -----------------------------------------------------------
    @property
    def pos(self) -> int:
        return self._p

    @property
    def abs_pos(self) -> int:
        return self._base + self._p

    def remaining(self) -> int:
        return len(self._d) - self._p

    def eof(self) -> bool:
        return self._p >= len(self._d)

    # -- primitives ---------------------------------------------------------
    def read(self, n: int) -> bytes:
        if n < 0:
            raise ParseError(f"negative read length {n}", self.abs_pos)
        if self._p + n > len(self._d):
            raise ParseError(
                f"truncated: need {n} bytes, have {self.remaining()}", self.abs_pos
            )
        b = self._d[self._p : self._p + n]
        self._p += n
        return b

    def u8(self) -> int:
        return self.read(1)[0]

    def s8(self) -> int:
        v = self.u8()
        return v - 0x100 if v & 0x80 else v

    def u16(self) -> int:
        b = self.read(2)
        return (b[0] << 8) | b[1]

    def s16(self) -> int:
        v = self.u16()
        return v - 0x10000 if v & 0x8000 else v

    def u32(self) -> int:
        b = self.read(4)
        return (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]

    def fourcc(self) -> str:
        return self.read(4).decode("latin-1")

    def uleb128(self) -> int:
        """Unsigned LEB128. IAMF caps the encoding at 8 bytes."""
        result = 0
        for i in range(8):
            if self.eof():
                raise ParseError("truncated leb128", self.abs_pos)
            byte = self.u8()
            result |= (byte & 0x7F) << (7 * i)
            if not (byte & 0x80):
                return result
        raise ParseError("leb128 exceeds 8 bytes", self.abs_pos)

    def cstring(self) -> str:
        """Null-terminated UTF-8 string (IAMF 'string' type, <= 128 bytes incl. NUL)."""
        start = self._p
        for _ in range(128):
            if self.eof():
                raise ParseError("unterminated string", self.abs_pos)
            if self.u8() == 0:
                return self._d[start : self._p - 1].decode("utf-8", "replace")
        raise ParseError("string exceeds 128 bytes (missing NUL)", self._base + start)

    def subreader(self, n: int) -> "ByteReader":
        """Carve out an n-byte sub-buffer (e.g. an OBU payload) with its own bounds."""
        chunk = self.read(n)
        return ByteReader(chunk, base=self.abs_pos - n)


class BitReader:
    """MSB-first bit reader over a ByteReader, for the few IAMF syntaxes whose
    fields are not byte-aligned (the position parameter data of IAMF v2.0.0:
    signed int (9), signed int (8), unsigned int (7) packed in sequence).

    Bytes are pulled from the underlying reader one at a time, so every read
    stays inside that reader's bounds and raises ParseError when they run out.
    Bits left in the last byte pulled are not given back: the IAMF syntaxes
    read through this end on a byte boundary."""

    def __init__(self, r: ByteReader) -> None:
        self._r = r
        self._acc = 0
        self._nbits = 0

    def u(self, width: int) -> int:
        while self._nbits < width:
            self._acc = (self._acc << 8) | self._r.u8()
            self._nbits += 8
        self._nbits -= width
        value = (self._acc >> self._nbits) & ((1 << width) - 1)
        self._acc &= (1 << self._nbits) - 1
        return value

    def s(self, width: int) -> int:
        v = self.u(width)
        return v - (1 << width) if v & (1 << (width - 1)) else v

    @property
    def bits_pending(self) -> int:
        """Bits pulled from the byte reader and not yet consumed."""
        return self._nbits


def split_bits(byte: int, *widths: int) -> list[int]:
    """Split one byte MSB-first into fields of the given bit widths.

    ``split_bits(0x10, 4, 1, 1, 2)`` -> [1, 0, 0, 0]  (loudspeaker_layout=1, ...).
    Widths must sum to 8.
    """
    if sum(widths) != 8:
        raise ValueError(f"bit widths must sum to 8, got {widths}")
    out = []
    shift = 8
    for w in widths:
        shift -= w
        out.append((byte >> shift) & ((1 << w) - 1))
    return out
