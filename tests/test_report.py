"""Report renderer contract tests (PRD R6) — json | text | html.

The JSON document is the machine contract downstream tools parse (and the MCP
server re-serves); the text/html renderers are the human surfaces. All
fixtures come from the clean-room builder — no toolchain, no samples.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(__file__)
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import sentinel                                                   # noqa: E402
from sentinel.engine import Report, validate, validate_bytes      # noqa: E402
from sentinel.findings import Finding, Severity                   # noqa: E402
from sentinel.report import (render, render_html, render_json,    # noqa: E402
                             render_text)
from fixtures.build import LayoutSpec, build, channel_spec        # noqa: E402


def _clean_report():
    spec = channel_spec("stereo")
    # advertise true peak so the report is finding-free (S-303 otherwise INFOs)
    spec.mixes[0].layouts = [LayoutSpec(0, -18.0, -6.0, -5.0)]
    return validate_bytes(build(spec))


def _failing_report():
    bad = channel_spec("7.1.4")
    bad.elements[0].layers[0].coupled_substream_count = 4
    return validate_bytes(build(bad))


# ----------------------------------------------------------------------- json

def test_render_json_schema_and_stream_block():
    doc = json.loads(render_json(_clean_report()))
    assert set(doc) == {"sentinel_version", "summary", "findings", "exit_code"}
    assert doc["sentinel_version"] == sentinel.__version__
    s = doc["summary"]
    assert s["result"] == "PASS" and doc["exit_code"] == 0
    st = s["stream"]
    assert st["primary_profile"] == "Base"
    assert st["codecs"] == ["ipcm"]
    assert st["audio_elements"] == 1 and st["mix_presentations"] == 1
    assert st["descriptor_bytes"] > 0


def test_render_json_error_report():
    doc = json.loads(render_json(validate("/no/such/file.iamf")))
    assert doc["exit_code"] == 2
    assert doc["summary"]["result"] == "ERROR"
    assert doc["summary"]["execution_error"]
    assert "stream" not in doc["summary"]


# ----------------------------------------------------------------------- text

def test_render_text_clean():
    out = render_text(_clean_report())
    assert out.startswith("Sentinel — IAMF conformance report")
    assert "no findings — clean." in out
    assert out.rstrip().endswith("exit code: 0")


def test_render_text_failing_carries_detail_lines():
    out = render_text(_failing_report())
    assert "[FAIL]" in out
    assert "           at: " in out                     # where sub-line
    assert "expected:" in out and "found:" in out       # expected/found sub-line
    assert "failure-modes:" in out                      # f_refs sub-line
    assert out.rstrip().endswith("exit code: 1")


def test_render_text_error_line():
    out = render_text(validate("/no/such/file.iamf"))
    assert "  ERROR    : " in out
    assert out.rstrip().endswith("exit code: 2")


# ----------------------------------------------------------------------- html

def test_render_html_escapes_finding_content():
    r = Report(source="synthetic", profile="generic", container="raw")
    r.findings.append(Finding(
        check_id="S-999", severity=Severity.FAIL,
        message="<script>alert(1)</script>",
        where="<b>elem</b>", expected="<i>", found="</i>"))
    out = render_html(r)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;b&gt;elem&lt;/b&gt;" in out


def test_render_html_result_colors():
    assert "#1a7f37" in render_html(_clean_report())            # PASS green
    assert "#c0392b" in render_html(_failing_report())          # FAIL red
    assert "#8250df" in render_html(validate("/no/such"))       # ERROR purple


# ------------------------------------------------------------------- dispatch

def test_render_dispatch_selects_renderer():
    r = _clean_report()
    assert render(r, "json") == render_json(r)
    assert render(r, "text") == render_text(r)
    assert render(r, "html") == render_html(r)


# --------------------------------------------------------------- Finding dict

def test_finding_to_dict_omits_unset_optionals():
    minimal = Finding(check_id="S-001", severity=Severity.INFO, message="m")
    d = minimal.to_dict()
    assert set(d) == {"check_id", "severity", "message"}

    full = Finding(check_id="S-001", severity=Severity.WARN, message="m",
                   where="w", expected="e", found="f", f_refs=("F4",))
    d = full.to_dict()
    assert d["where"] == "w" and d["expected"] == "e" and d["found"] == "f"
    assert d["severity"] == "WARN"
