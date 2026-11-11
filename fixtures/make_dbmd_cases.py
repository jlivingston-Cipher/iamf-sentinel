#!/usr/bin/env python3
"""Write the golden `dbmd` cases both readers are held to.

    python3 fixtures/make_dbmd_cases.py OUT.json

Each case carries the bytes (hex) and what sentinel's reader makes of them:
`kind: "chunk"` is a dbmd payload for `sentinel.dbmd.parse_dbmd` (C++:
`dbmd::parse`); `kind: "wav"` is a whole ADM BWF for `sentinel.bwf.adm_info`'s
`dolbyMetadata` (C++: `adm::parseAdmImage`'s `summary.dolbyMetadata`).
Inseglet's unit.dbmd reads this file and must produce the same JSON.
"""
import json
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fixtures import dbmd_build as B  # noqa: E402
from sentinel.dbmd import parse_dbmd  # noqa: E402
from sentinel.bwf import adm_info  # noqa: E402


def full(binaural=(0, 1, 2, 3), seg10=None, **kw):
    s10 = seg10 if seg10 is not None else B.segment10(list(binaural))
    return B.dbmd([B.segment(9, B.segment9(**kw)), B.segment(10, s10)])


trims = ["auto"] * 9
trims[1] = (-3.0, -1.5, 0.0, 0x80 | 127, 64)
trims[7] = (-0.5, 0.0, -6.0, 3, 0x80 | 1)
CHUNKS = {
    "placeholder": bytes.fromhex("00000001") + bytes(28),
    "version_1_15_2_0": struct.pack("<I", 0x010F0200) + b"\0",
    "version_2_refused": struct.pack("<I", 0x02000000) + B.segment(9, B.segment9()) + b"\0",
    "short": b"\x01\x00",
    "full_default": full(),
    "full_fps25_ffoa_warp1_dm4_ph1": full(fps=3, ffoa=(0, 1, 2_500_000), warp=1, downmix5to2=4, phase90=1),
    "full_negative_ffoa_fps_df": full(fps=4, ffoa=(0xFE, 30, 123)),
    "full_fill00": full(fill=0x00),
    "full_fillff": full(fill=0xFF),
    "binaural_all_codes": full(binaural=[0, 1, 2, 3, 4, 7]),
    "manual_trims_headtrack": B.dbmd([B.segment(10, B.segment10([2, 3, 1], trims=trims,
                                     trim_bypass=[0, 1, 2], head_track=[1, 2, 3]))]),
    "bad_checksum": B.dbmd([B.segment(9, B.segment9(), bad_checksum=True)]),
    "two_byte_checksum": B.dbmd([B.segment(1, bytes(300), two_byte_checksum=True)]),
    "wrong_sync": B.dbmd([B.segment(10, B.segment10([1, 2], sync=0xF8726FBC))]),
    "seg10_short_for_count": B.dbmd([B.segment(10, B.segment10([1, 1], object_count=9))]),
    "seg9_truncated": B.dbmd([B.segment(9, B.segment9())])[:100],
    "unterminated": B.dbmd([B.segment(9, B.segment9())], terminate=False),
    "reserved_and_unknown_segments": B.dbmd([B.segment(3, bytes(20)), B.segment(42, bytes(5)),
                                             B.segment(9, B.segment9(fps=3, extra=6))]),
    "size_zero": B.dbmd([B.segment(8, b"", declared_size=0)]),
    "seg10_extra": B.dbmd([B.segment(10, B.segment10([0, 1], extra=3))]),
}
WAVS = {
    "wav_riff_4ch": B.adm_wav(channels=4, dbmd_payload=full(binaural=[0, 1, 2, 3])),
    "wav_bw64_2ch_count_mismatch": B.adm_wav(channels=2, container=b"BW64",
                                             dbmd_payload=full(binaural=[3, 3, 3])),
    "wav_rf64_placeholder": B.adm_wav(channels=2, container=b"RF64",
                                      dbmd_payload=bytes.fromhex("00000001") + bytes(28)),
}

cases = []
for name, b in CHUNKS.items():
    cases.append({"name": name, "kind": "chunk", "hex": b.hex(), "expect": parse_dbmd(b)})
with tempfile.TemporaryDirectory() as td:
    for name, b in WAVS.items():
        p = os.path.join(td, name + ".wav")
        open(p, "wb").write(b)
        cases.append({"name": name, "kind": "wav", "hex": b.hex(),
                      "expect": adm_info(p)["dolbyMetadata"]})
with open(sys.argv[1], "w") as fh:
    json.dump({"generator": "iamf-sentinel fixtures/make_dbmd_cases.py", "cases": cases}, fh, indent=1)
print(f"{len(cases)} cases")
