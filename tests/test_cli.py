"""CLI contract tests (PRD R6) — the shipped `sentinel` entry point.

Everything here is toolchain-free: fixtures come from the clean-room builder,
--l3 paths are exercised only for their error contracts (the plugin-absent and
no-oracle arms), and all assertions are on exit codes, stable prefixes, and
the machine-readable JSON shape — not on full message strings.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from sentinel.cli import main, _iter_media                       # noqa: E402
from sentinel.findings import REGISTRY                           # noqa: E402
from fixtures.build import LayoutSpec, build, channel_spec       # noqa: E402


@pytest.fixture
def clean_file(tmp_path):
    spec = channel_spec("stereo")
    # advertise true peak so the report is finding-free (S-303 otherwise INFOs)
    spec.mixes[0].layouts = [LayoutSpec(0, -18.0, -6.0, -5.0)]
    p = tmp_path / "clean.iamf"
    p.write_bytes(build(spec))
    return str(p)


@pytest.fixture
def failing_file(tmp_path):
    bad = channel_spec("7.1.4")
    bad.elements[0].layers[0].coupled_substream_count = 4       # F4-class misroute
    p = tmp_path / "bad.iamf"
    p.write_bytes(build(bad))
    return str(p)


@pytest.fixture
def warn_file(tmp_path):
    spec = channel_spec("stereo")
    spec.mixes[0].annotation = "test_mix_pres"                  # S-208 WARN only
    p = tmp_path / "warn.iamf"
    p.write_bytes(build(spec))
    return str(p)


# ------------------------------------------------------------------- validate

def test_cli_validate_text_pass_and_fail_exit_codes(clean_file, failing_file, capsys):
    assert main(["validate", clean_file]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Sentinel — IAMF conformance report")
    assert "no findings — clean." in out

    assert main(["validate", failing_file]) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out


def test_cli_validate_json_to_file_writes_no_chatter(clean_file, tmp_path, capsys):
    out_path = tmp_path / "report.json"
    assert main(["validate", clean_file, "--format", "json",
                 "-o", str(out_path)]) == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["exit_code"] == 0
    assert doc["summary"]["result"] == "PASS"
    # json to a file stays machine-clean on stdout (cli.py json branch)
    assert capsys.readouterr().out == ""


def test_cli_validate_text_to_file_reports_the_write(clean_file, tmp_path, capsys):
    out_path = tmp_path / "report.txt"
    assert main(["validate", clean_file, "-o", str(out_path)]) == 0
    assert f"wrote text report to {out_path}" in capsys.readouterr().out
    assert out_path.read_text(encoding="utf-8").startswith("Sentinel — IAMF conformance report")


def test_cli_validate_missing_file_is_exit_2(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "no-such.iamf"),
                 "--format", "json"]) == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["summary"]["result"] == "ERROR"
    assert "execution_error" in doc["summary"]


def test_cli_validate_strict_promotes_warn(warn_file, capsys):
    assert main(["validate", warn_file]) == 0                   # WARN passes by default
    capsys.readouterr()
    assert main(["validate", warn_file, "--strict"]) == 1       # --strict fails it


def test_cli_l3_without_pro_is_actionable_exit_2(clean_file, capsys, monkeypatch):
    # Simulate an install without the pro plugin: block the import.
    monkeypatch.setitem(sys.modules, "sentinel_pro", None)
    monkeypatch.setitem(sys.modules, "sentinel_pro.oracle", None)
    assert main(["validate", clean_file, "--l3"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "iamf-sentinel-pro" in err


# --------------------------------------------------------------------- checks

def test_cli_checks_lists_every_registry_id(capsys):
    assert main(["checks"]) == 0
    out = capsys.readouterr().out
    for cid in REGISTRY:
        assert cid in out


def test_cli_checks_verbose_adds_descriptions(capsys):
    main(["checks"])
    brief = capsys.readouterr().out
    main(["checks", "-v"])
    verbose = capsys.readouterr().out
    assert len(verbose) > len(brief)


# ----------------------------------------------------------------------- diff

def test_cli_diff_text_identical(clean_file, capsys):
    assert main(["diff", clean_file, clean_file]) == 0
    out = capsys.readouterr().out
    assert "verdict: IDENTICAL" in out


def test_cli_diff_json_shape(clean_file, failing_file, capsys):
    rc = main(["diff", clean_file, failing_file, "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"a", "b", "verdict", "entries", "exit_code"}
    assert doc["verdict"] == "DIFFERENT"
    assert doc["exit_code"] == rc == 1
    assert all({"kind", "where", "a", "b"} <= set(e) for e in doc["entries"])


# ---------------------------------------------------------------------- batch

def test_cli_batch_rollup_text(clean_file, failing_file, tmp_path, capsys):
    root = tmp_path                                             # holds both fixtures
    rc = main(["batch", str(root)])
    out = capsys.readouterr().out
    assert rc == 1                                              # worst exit propagates
    assert "Sentinel batch —" in out
    assert "1/2 passed" in out
    assert "worst exit: 1" in out


def test_cli_batch_json_shape(clean_file, tmp_path, capsys):
    rc = main(["batch", str(tmp_path), "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert doc["files"] == 1 and doc["worst_exit"] == 0
    assert doc["results"][0]["result"] == "PASS"


def test_cli_batch_single_file_root(clean_file, capsys):
    # _iter_media's isfile branch: a file path is a one-entry batch
    assert main(["batch", clean_file]) == 0
    assert "1/1 passed" in capsys.readouterr().out


def test_iter_media_filters_and_sorts(tmp_path):
    (tmp_path / "b.iamf").write_bytes(b"x")
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")
    got = [os.path.basename(p) for p in _iter_media(str(tmp_path))]
    assert got == ["a.mp4", "b.iamf"]


def test_cli_output_files_are_utf8(clean_file, tmp_path):
    """Named regression (doc 97b): `--output` must write UTF-8, not the
    locale encoding.

    The text report opens with "Sentinel — IAMF conformance report" and the
    HTML report declares UTF-8 in its own header while writing middots and
    em dashes. An unqualified text write uses `locale.getpreferredencoding()`
    — cp1252 on Windows — so the bytes on disk contradict the charset the
    file announces. Reading back as UTF-8 is what makes that fail loudly.
    """
    for fmt, ext in (("text", "txt"), ("html", "html")):
        out = tmp_path / f"report.{ext}"
        main(["validate", clean_file, "--format", fmt, "--output", str(out)])
        raw = out.read_bytes()
        assert b"\r\n" not in raw, f"{fmt} report wrote CRLF"
        text = raw.decode("utf-8")          # raises if the write was locale-encoded
        assert "—" in text, f"{fmt} report lost its non-ASCII content"
