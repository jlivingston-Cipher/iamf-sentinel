"""Report renderers: json | text | html (PRD R6)."""

from __future__ import annotations
import html
import json

from . import __version__
from .engine import Report

_SEV_COLOR = {"FAIL": "#c0392b", "WARN": "#b8860b", "INFO": "#2b78c4"}


def _summary_dict(report: Report) -> dict:
    mod = report.model
    d = {
        "source": report.source,
        "profile": report.profile,
        "container": report.container,
        "result": "PASS" if report.passed() else ("ERROR" if report.execution_error else "FAIL"),
        "counts": report.counts(),
    }
    if report.execution_error:
        d["execution_error"] = report.execution_error
    if mod and mod.sequence_header:
        from . import model as m
        d["stream"] = {
            "primary_profile": m.PROFILE_NAME.get(mod.sequence_header.primary_profile,
                                                  mod.sequence_header.primary_profile),
            "codecs": sorted({cc.codec_id for cc in mod.codec_configs.values()}),
            "audio_elements": len(mod.audio_elements),
            "mix_presentations": len(mod.mix_presentations),
            "descriptor_bytes": mod.descriptor_bytes,
            "audio_frames": len(mod.audio_frames),
        }
    return d


def render_json(report: Report, *, indent: int = 2) -> str:
    doc = {
        "sentinel_version": __version__,
        "summary": _summary_dict(report),
        "findings": [f.to_dict() for f in report.sorted_findings()],
        "exit_code": report.exit_code(),
    }
    return json.dumps(doc, indent=indent)


def render_text(report: Report, *, color: bool = False) -> str:
    lines = []
    s = _summary_dict(report)
    lines.append("Sentinel — IAMF conformance report")
    lines.append(f"  source   : {report.source}")
    lines.append(f"  profile  : {report.profile}   container: {report.container}")
    if "stream" in s:
        st = s["stream"]
        lines.append(f"  stream   : {st['primary_profile']} profile, codec {','.join(st['codecs'])}, "
                     f"{st['audio_elements']} element(s), {st['mix_presentations']} mix pres, "
                     f"{st['descriptor_bytes']}B descriptor")
    if report.execution_error:
        lines.append(f"  ERROR    : {report.execution_error}")
    c = report.counts()
    lines.append(f"  result   : {s['result']}   "
                 f"({c['FAIL']} FAIL, {c['WARN']} WARN, {c['INFO']} INFO)")
    lines.append("")
    if not report.findings:
        lines.append("  no findings — clean.")
    for f in report.sorted_findings():
        tag = f.severity.label
        head = f"  [{tag}] {f.check_id}  {f.message}"
        lines.append(head)
        if f.where:
            lines.append(f"           at: {f.where}")
        if f.expected is not None or f.found is not None:
            lines.append(f"           expected: {f.expected}   found: {f.found}")
        if f.f_refs:
            lines.append(f"           failure-modes: {', '.join(f.f_refs)}")
    lines.append("")
    lines.append(f"exit code: {report.exit_code()}")
    return "\n".join(lines)


def render_html(report: Report) -> str:
    s = _summary_dict(report)
    c = report.counts()
    result = s["result"]
    result_color = "#1a7f37" if result == "PASS" else ("#8250df" if result == "ERROR" else "#c0392b")
    rows = []
    for f in report.sorted_findings():
        col = _SEV_COLOR[f.severity.label]
        detail = ""
        if f.expected is not None or f.found is not None:
            detail += (f"<div class='kv'><span>expected</span> {html.escape(str(f.expected))}"
                       f" &nbsp; <span>found</span> {html.escape(str(f.found))}</div>")
        if f.where:
            detail += f"<div class='where'>at {html.escape(f.where)}</div>"
        if f.f_refs:
            detail += f"<div class='fref'>{', '.join(html.escape(x) for x in f.f_refs)}</div>"
        rows.append(f"""
        <tr>
          <td><span class="sev" style="background:{col}">{f.severity.label}</span></td>
          <td class="cid">{html.escape(f.check_id)}</td>
          <td>{html.escape(f.message)}{detail}</td>
        </tr>""")
    stream_html = ""
    if "stream" in s:
        st = s["stream"]
        stream_html = (f"{st['primary_profile']} profile · codec {', '.join(st['codecs'])} · "
                       f"{st['audio_elements']} element(s) · {st['mix_presentations']} mix pres · "
                       f"{st['descriptor_bytes']}B descriptor")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Sentinel report — {html.escape(report.source)}</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;color:#1b1f24;background:#fbfbfd}}
 h1{{font-size:1.25rem;margin:0 0 .25rem}}
 .meta{{color:#57606a;margin-bottom:1rem}}
 .result{{display:inline-block;color:#fff;padding:.15rem .6rem;border-radius:.4rem;background:{result_color};font-weight:600}}
 .counts span{{display:inline-block;margin-right:1rem;color:#57606a}}
 table{{border-collapse:collapse;width:100%;margin-top:1rem;background:#fff;border:1px solid #d0d7de;border-radius:.5rem;overflow:hidden}}
 th,td{{text-align:left;padding:.55rem .7rem;border-bottom:1px solid #eaeef2;vertical-align:top}}
 th{{background:#f6f8fa;font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:#57606a}}
 .sev{{color:#fff;padding:.05rem .45rem;border-radius:.3rem;font-size:.72rem;font-weight:700}}
 .cid{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#57606a;white-space:nowrap}}
 .kv span,.where,.fref{{color:#57606a;font-size:.82rem}}
 .kv{{margin-top:.3rem}} .fref{{margin-top:.2rem;font-style:italic}}
</style></head><body>
<h1>Sentinel — IAMF conformance report</h1>
<div class="meta">{html.escape(report.source)} &nbsp;·&nbsp; profile <b>{html.escape(report.profile)}</b>
 &nbsp;·&nbsp; {html.escape(report.container)} &nbsp;·&nbsp; {html.escape(stream_html)}</div>
<div><span class="result">{result}</span></div>
<div class="counts" style="margin-top:.6rem">
 <span><b>{c['FAIL']}</b> FAIL</span><span><b>{c['WARN']}</b> WARN</span><span><b>{c['INFO']}</b> INFO</span>
 <span>exit {report.exit_code()}</span></div>
<table><thead><tr><th>sev</th><th>check</th><th>finding</th></tr></thead>
<tbody>{''.join(rows) if rows else '<tr><td colspan=3>no findings — clean.</td></tr>'}</tbody></table>
</body></html>"""


def render(report: Report, fmt: str) -> str:
    if fmt == "json":
        return render_json(report)
    if fmt == "html":
        return render_html(report)
    return render_text(report)
