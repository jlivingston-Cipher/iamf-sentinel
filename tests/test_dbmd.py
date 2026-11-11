"""The dbmd reader (sentinel.dbmd) and the ADM chunk walker (sentinel.bwf).

No Dolby-written master is available to these tests, so they prove what can
be proved without one: the framing of EBU Tech 3285 Supplement 6 (version,
segments, checksum, terminator), each mapped field read from its own
position and from nowhere else (unread spans are filled with 0xA5, and every
field is moved alone to show the reader follows it), the tables in code
order (the Far/Mid trap), and that every refusal says what it refused.
"""

from __future__ import annotations

import json
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fixtures import dbmd_build as B  # noqa: E402
from sentinel import bwf  # noqa: E402
from sentinel.cli import main  # noqa: E402
from sentinel.dbmd import parse_dbmd, checksum  # noqa: E402


def _full(binaural=(0, 1, 2, 3), **kw9):
    return B.dbmd([B.segment(9, B.segment9(**kw9)),
                   B.segment(10, B.segment10(list(binaural)))])


# --- framing ----------------------------------------------------------------

def test_placeholder_reads_as_empty():
    # Our own placeholder (Inseglet adm_bwf.h, iamf-adm-corpus): a version word, then zeroes.
    d = parse_dbmd(bytes.fromhex("00000001") + bytes(28))
    assert d["readable"] and d["terminated"] and d["version"] == "1.0.0.0"
    assert d["segments"] == [] and d["atmos"] is None and d["supplemental"] is None


def test_version_word_is_little_endian():
    d = parse_dbmd(struct.pack("<I", 0x010F0200) + b"\0")
    assert d["version"] == "1.15.2.0"   # Tech 3285 s6's own example


def test_major_version_above_one_refused_and_says_so():
    d = parse_dbmd(struct.pack("<I", 0x02000000) + B.segment(9, B.segment9()) + b"\0")
    assert d["readable"] is False and d["atmos"] is None
    assert any("above 1" in n for n in d["notes"])


def test_checksum_matches_tech3285_pseudocode():
    p = bytes(range(1, 40))
    low, two = checksum(len(p), p)
    assert (low + len(p) + sum(p)) & 0xFF == 0
    assert low == B.checksum(len(p), p)
    seg = B.segment(1, p)
    d = parse_dbmd(B.dbmd([seg]))
    assert d["segments"][0]["checksum"] == "ok"


def test_checksum_two_byte_reading_reported_as_such():
    p = bytes(300)   # size 300 = 0x012C: the two readings differ
    d = parse_dbmd(B.dbmd([B.segment(1, p, two_byte_checksum=True)]))
    assert d["segments"][0]["checksum"] == "ok (two-byte size reading)"


def test_checksum_mismatch_reported():
    d = parse_dbmd(B.dbmd([B.segment(9, B.segment9(), bad_checksum=True)]))
    assert d["segments"][0]["checksum"].startswith("mismatch")
    assert d["atmos"]["frameRate"]["code"] == 2   # a bad checksum is a note, not a refusal


def test_unterminated_and_truncated_segments_say_so():
    d = parse_dbmd(B.dbmd([B.segment(9, B.segment9())], terminate=False))
    assert not d["terminated"] and any("no end segment" in n for n in d["notes"])
    raw = B.dbmd([B.segment(9, B.segment9())])[:100]
    d = parse_dbmd(raw)
    seg = d["segments"][0]
    assert any("remain" in n for n in seg["notes"])
    assert any("the field map reads 168" in n for n in d["atmos"]["notes"])


def test_unknown_and_reserved_segments_are_listed_and_skipped():
    d = parse_dbmd(B.dbmd([B.segment(3, bytes(20)), B.segment(42, bytes(5)),
                           B.segment(9, B.segment9(fps=3))]))
    assert [s["id"] for s in d["segments"]] == [3, 42, 9]
    assert d["segments"][1]["name"] == "reserved"
    assert d["atmos"]["frameRate"]["name"] == "25"


# --- segment 9 ----------------------------------------------------------------

@pytest.mark.parametrize("fps,name,dropf", [(0, "not indicated", None), (1, "23.976", False),
                                            (2, "24", False), (3, "25", False),
                                            (4, "29.97 DF", True), (5, "29.97 NDF", False),
                                            (6, "30", False)])
def test_frame_rate_table(fps, name, dropf):
    a = parse_dbmd(_full(fps=fps))["atmos"]
    assert a["frameRate"]["name"] == name and a["frameRate"]["dropFrame"] == dropf


def test_ffoa_unassigned_and_set():
    assert parse_dbmd(_full(ffoa=None))["atmos"]["firstFrameOfAction"] is None
    f = parse_dbmd(_full(ffoa=(0, 1, 2_500_000)))["atmos"]["firstFrameOfAction"]
    assert f["seconds"] == pytest.approx(85.0) and not f["negative"]
    f = parse_dbmd(_full(ffoa=(0xFE, 0, 0)))["atmos"]["firstFrameOfAction"]
    assert f["negative"] and f["seconds"] == pytest.approx(-7200.0)


@pytest.mark.parametrize("code,name", list(enumerate(
    ["not indicated (Lo/Ro)", "Lo/Ro", "Lt/Rt (Dolby Pro Logic)",
     "Lt/Rt (Dolby Pro Logic II)", "direct stereo render"])))
def test_downmix_5to2_table(code, name):
    assert parse_dbmd(_full(downmix5to2=code))["atmos"]["downmix5to2"]["name"] == name


@pytest.mark.parametrize("code,name", list(enumerate(
    ["Direct Render", "Direct Render with room balance", "Dolby Pro Logic IIx",
     "Standard (Lo/Ro)", "not indicated"])))
def test_warp_mode_table(code, name):
    assert parse_dbmd(_full(warp=code))["atmos"]["downmix5_1x"]["name"] == name


def test_tool_name_and_version():
    a = parse_dbmd(_full(tool="Dolby Atmos Renderer", tool_version=(5, 2, 1)))["atmos"]
    assert a["contentCreationTool"] == "Dolby Atmos Renderer"
    assert a["contentCreationToolVersion"] == "5.2.1"


def test_each_segment9_field_moves_alone():
    """Change one field; only that field's reading may change (position control)."""
    base = parse_dbmd(_full())["atmos"]
    for kw, key in [({"fps": 6}, "frameRate"), ({"downmix5to2": 4}, "downmix5to2"),
                    ({"phase90": 1}, "phaseShift90_5to2"), ({"warp": 3}, "downmix5_1x"),
                    ({"ffoa": (1, 0, 0)}, "firstFrameOfAction"),
                    ({"bed_distribution": 2}, "bedDistribution")]:
        got = parse_dbmd(_full(**kw))["atmos"]
        moved = [k for k in base if base[k] != got[k]]
        assert moved == [key], (kw, moved)


def test_fill_bytes_do_not_leak_into_fields():
    """The same fields with 0x00 and 0xFF in the unread spans read the same."""
    a = parse_dbmd(_full(fill=0x00))["atmos"]
    b = parse_dbmd(_full(fill=0xFF))["atmos"]
    for k in ("frameRate", "downmix5to2", "phaseShift90_5to2", "downmix5_1x",
              "firstFrameOfAction", "contentCreationTool"):
        assert a[k] == b[k], k


# --- segment 10 ---------------------------------------------------------------

def test_binaural_table_far_and_mid_in_code_order():
    s = parse_dbmd(_full(binaural=[0, 1, 2, 3, 4]))["supplemental"]
    assert [m["name"] for m in s["binaural"]] == [
        "Off", "Near", "Far", "Mid", "not indicated (Mid)"]
    assert s["objectCount"] == 5 and s["syncOk"]


def test_wrong_sync_refused_and_says_so():
    s = parse_dbmd(B.dbmd([B.segment(10, B.segment10([1, 2], sync=0xF8726FBC))]))["supplemental"]
    assert s["syncOk"] is False and "binaural" not in s
    assert any("expected 0xF8726FBD" in n for n in s["notes"])


def test_manual_trims_read():
    trims = ["auto"] * 9
    trims[1] = (-3.0, -1.5, 0.0, 0x80 | 127, 64)
    s = parse_dbmd(B.dbmd([B.segment(10, B.segment10([0, 0], trims=trims))]))["supplemental"]
    t = s["trims"][1]
    assert not t["auto"] and t["centreDb"] == -3.0 and t["surroundDb"] == -1.5
    assert t["balanceOverheadFloor"] == -1.0 and t["balanceListener"] == pytest.approx(64 / 127, abs=1e-4)
    assert all(x["auto"] for i, x in enumerate(s["trims"]) if i != 1)


def test_head_track_and_trim_bypass_do_not_move_binaural():
    a = parse_dbmd(B.dbmd([B.segment(10, B.segment10([2, 3]))]))["supplemental"]
    b = parse_dbmd(B.dbmd([B.segment(10, B.segment10([2, 3], head_track=[3, 3],
                                                     trim_bypass=[1, 2]))]))["supplemental"]
    assert [m["code"] for m in a["binaural"]] == [m["code"] for m in b["binaural"]] == [2, 3]
    assert [m["headTrackMode"] for m in b["binaural"]] == [3, 3]
    assert [(t["code"], t["name"]) for t in b["trimBypass"]] == [
        (1, "trim ignored"), (2, "not indicated")]


def test_segment10_short_for_its_object_count_says_so():
    s = parse_dbmd(B.dbmd([B.segment(10, B.segment10([1, 1], object_count=9))]))["supplemental"]
    assert "binaural" not in s and any("9 tracks need" in n for n in s["notes"])


# --- the chunk walker and the CLI -------------------------------------------

def test_adm_info_riff_maps_binaural_to_chna(tmp_path):
    p = tmp_path / "m.wav"
    p.write_bytes(B.adm_wav(channels=4, dbmd_payload=_full(binaural=[0, 1, 2, 3])))
    info = bwf.adm_info(str(p))
    assert info["container"] == "RIFF" and info["isAdm"]
    assert info["format"] == {"formatTag": 1, "channels": 4, "sampleRate": 48000, "bitDepth": 24}
    modes = info["dolbyMetadata"]["supplemental"]["binaural"]
    assert [(m["chnaTrackIndex"], m["uid"], m["name"]) for m in modes] == [
        (1, "ATU_00000001", "Off"), (2, "ATU_00000002", "Near"),
        (3, "ATU_00000003", "Far"), (4, "ATU_00000004", "Mid")]
    assert info["dolbyMetadata"]["notes"] == []


def test_adm_info_count_mismatch_noted(tmp_path):
    p = tmp_path / "m.wav"
    p.write_bytes(B.adm_wav(channels=4, dbmd_payload=_full(binaural=[0, 1])))
    notes = bwf.adm_info(str(p))["dolbyMetadata"]["notes"]
    assert any("segment 10 names 2 tracks; fmt has 4" in n for n in notes)


def test_adm_info_bw64_and_rf64_walk_past_ds64(tmp_path):
    for c in (b"BW64", b"RF64"):
        p = tmp_path / f"m_{c.decode()}.wav"
        p.write_bytes(B.adm_wav(channels=2, container=c, dbmd_payload=_full(binaural=[1, 1])))
        info = bwf.adm_info(str(p))
        assert info["container"] == c.decode()
        assert [x["id"] for x in info["chunks"]] == ["ds64", "fmt ", "dbmd", "chna", "axml", "data"]
        assert info["chunks"][-1]["size"] == 2 * 3 * 480
        assert info["ds64"]["riffSize"] == p.stat().st_size - 8
        assert info["dolbyMetadata"]["atmos"]["frameRate"]["name"] == "24"


def test_adm_info_absent_dbmd_and_not_a_wave(tmp_path):
    p = tmp_path / "m.wav"
    p.write_bytes(B.adm_wav())
    assert bwf.adm_info(str(p))["dolbyMetadata"] is None
    q = tmp_path / "x.wav"
    q.write_bytes(b"OggS" + bytes(40))
    assert bwf.adm_info(str(q))["container"] is None


def test_cli_adm_info_json_and_text(tmp_path, capsys):
    p = tmp_path / "m.wav"
    p.write_bytes(B.adm_wav(channels=2, dbmd_payload=_full(binaural=[2, 3], warp=1)))
    assert main(["adm-info", str(p), "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dolbyMetadata"]["atmos"]["downmix5_1x"]["name"] == "Direct Render with room balance"
    assert main(["adm-info", str(p)]) == 0
    txt = capsys.readouterr().out
    assert "headphone render modes: Far x1, Mid x1" in txt
    assert "not yet confirmed on a master written by Dolby's renderer" in txt
    q = tmp_path / "x.wav"
    q.write_bytes(b"junk" * 10)
    assert main(["adm-info", str(q)]) == 2
