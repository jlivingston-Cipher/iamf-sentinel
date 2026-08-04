"""CLI contract for `sentinel intent-compare` (B1-R3, doc 123).

Toolchain-free: only the error contracts and the registry surface are
exercised here — the working path needs the pro plugin and its fixture
builders and lives in iamf-sentinel-pro/tests/. New file rather than an
edit to test_cli.py (zero-existing-test-edit discipline).
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from sentinel.cli import main                                     # noqa: E402
from sentinel.findings import REGISTRY, Severity                  # noqa: E402


def test_intent_compare_without_pro_is_actionable_exit_2(tmp_path, capsys,
                                                         monkeypatch):
    # Simulate an install without the pro plugin: block the import.
    monkeypatch.setitem(sys.modules, "sentinel_pro", None)
    monkeypatch.setitem(sys.modules, "sentinel_pro.intent_compare", None)
    sidecar = tmp_path / "x.intent.json"
    sidecar.write_text("{}", encoding="utf-8")
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    assert main(["intent-compare", str(sidecar), str(wav)]) == 2
    err = capsys.readouterr().err
    assert "iamf-sentinel-pro" in err


def test_intent_compare_requires_both_positionals():
    with pytest.raises(SystemExit) as e:
        main(["intent-compare"])
    assert e.value.code == 2


def test_s34x_rows_present_and_fail_severity():
    for cid in ("S-340", "S-341", "S-342", "S-343", "S-344", "S-345",
                "S-346"):
        assert cid in REGISTRY
        assert REGISTRY[cid].default_severity == Severity.FAIL
