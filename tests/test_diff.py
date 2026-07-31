"""Descriptor-diff contract tests — verdicts, entries, and the text renderer.

Complements the three diff_files scenarios in test_sentinel.py with the
branches those don't reach: verdict strings, the loudness-only verdict, the
codec and loudness-layout structural entries, the ambisonics element summary,
DiffEntry.to_dict rounding, and render_diff_text. Toolchain-free throughout
(render_compare's real-decoder half lives with the toolchain suites).
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from sentinel.diff import DiffEntry, diff_files, render_diff_text  # noqa: E402
from fixtures.build import (LayoutSpec, build, channel_spec,       # noqa: E402
                            scene_spec)


def _write(tmp_path, name, spec):
    p = tmp_path / name
    p.write_bytes(build(spec))
    return str(p)


# ------------------------------------------------------------------- verdicts

def test_verdict_identical(tmp_path):
    a = _write(tmp_path, "a.iamf", channel_spec("stereo"))
    res = diff_files(a, a)
    assert res.verdict() == "IDENTICAL"
    assert res.exit_code() == 0
    assert res.entries == []


def test_verdict_different_on_structural(tmp_path):
    a = _write(tmp_path, "a.iamf", channel_spec("stereo"))
    b = _write(tmp_path, "b.iamf", channel_spec("5.1"))
    res = diff_files(a, b)
    assert res.verdict() == "DIFFERENT"
    assert res.exit_code() == 1
    assert res.structural_diffs


def test_verdict_loudness_only(tmp_path):
    sa = channel_spec("stereo")
    sb = channel_spec("stereo")
    sb.mixes[0].layouts = [LayoutSpec(0, -14.0, -6.0)]      # −18 → −14 LKFS
    a = _write(tmp_path, "a.iamf", sa)
    b = _write(tmp_path, "b.iamf", sb)
    res = diff_files(a, b)
    assert res.verdict() == "STRUCTURALLY-EQUAL (loudness differs)"
    assert res.exit_code() == 0        # loudness-only differences do not fail the diff
    assert not res.structural_diffs
    [entry] = res.loudness_diffs
    assert entry.where == "integrated @ Stereo"
    assert entry.delta is not None and abs(entry.delta - 4.0) < 0.01


# -------------------------------------------------------------------- entries

def test_codec_mismatch_entry(tmp_path):
    sa = channel_spec("stereo")
    sb = channel_spec("stereo")
    sb.codec_id = "Opus"
    a = _write(tmp_path, "a.iamf", sa)
    b = _write(tmp_path, "b.iamf", sb)
    res = diff_files(a, b)
    codecs = [e for e in res.structural_diffs if e.where == "codecs"]
    assert codecs, [e.to_dict() for e in res.entries]
    assert "ipcm" in codecs[0].a and "Opus" in codecs[0].b


def test_loudness_layout_present_absent(tmp_path):
    sa = channel_spec("7.1.4")                              # stereo + native layouts
    sb = channel_spec("7.1.4")
    sb.mixes[0].layouts = [LayoutSpec(0, -18.0, -6.0)]      # stereo only
    a = _write(tmp_path, "a.iamf", sa)
    b = _write(tmp_path, "b.iamf", sb)
    res = diff_files(a, b)
    missing = [e for e in res.structural_diffs
               if e.where.startswith("loudness layout")]
    assert missing
    assert (missing[0].a, missing[0].b) == ("present", "absent")


def test_ambisonics_element_summary(tmp_path):
    a = _write(tmp_path, "a.iamf", scene_spec(1))
    b = _write(tmp_path, "b.iamf", scene_spec(3))
    res = diff_files(a, b)
    elems = [e for e in res.structural_diffs if "audio_element" in e.where]
    assert elems
    assert "scene/ambi order=1" in elems[0].a
    assert "scene/ambi order=3" in elems[0].b


# ------------------------------------------------------------------- to_dict

def test_diff_entry_to_dict_rounds_delta():
    e = DiffEntry("LOUDNESS", "integrated @ Stereo", "-18.00 LKFS",
                  "-14.00 LKFS", delta=4.000049)
    d = e.to_dict()
    assert d["kind"] == "LOUDNESS" and d["where"] == "integrated @ Stereo"
    assert d["delta"] == 4.0


def test_diff_entry_to_dict_omits_absent_delta():
    d = DiffEntry("STRUCTURAL", "codecs", "['ipcm']", "['Opus']").to_dict()
    assert "delta" not in d or d["delta"] is None


# -------------------------------------------------------------- text renderer

def test_render_diff_text_identical(tmp_path):
    a = _write(tmp_path, "a.iamf", channel_spec("stereo"))
    out = render_diff_text(diff_files(a, a))
    assert out.startswith("Sentinel diff")
    assert "verdict: IDENTICAL" in out
    assert "descriptor structure and loudness identical." in out
    assert out.rstrip().endswith("exit code: 0")


def test_render_diff_text_entry_lines_and_delta(tmp_path):
    sa = channel_spec("stereo")
    sb = channel_spec("stereo")
    sb.mixes[0].layouts = [LayoutSpec(0, -14.0, -6.0)]
    a = _write(tmp_path, "a.iamf", sa)
    b = _write(tmp_path, "b.iamf", sb)
    out = render_diff_text(diff_files(a, b))
    assert "[LOUDNESS] integrated @ Stereo:" in out
    assert "(Δ +4.00)" in out
    assert out.rstrip().endswith("exit code: 0")   # loudness-only: informational
