"""Report renderers: json | text | html (PRD R6)."""

from __future__ import annotations
import html
import json

from . import __version__
from . import model as m
from .engine import Report

_SEV_COLOR = {"FAIL": "#c0392b", "WARN": "#b8860b", "INFO": "#2b78c4"}

_POLAR_AXES = ("azimuth", "elevation", "distance")
_CARTESIAN_AXES = ("x", "y", "z")


def _object_facts(mod: m.IAMFModel) -> list[dict]:
    """The object-based elements, as read. num_objects is None when the
    element's config bytes are not an ObjectsConfig."""
    return [{"audio_element_id": aid,
             "num_objects": ae.objects.num_objects if ae.objects else None,
             "num_substreams": ae.num_substreams}
            for aid, ae in mod.audio_elements.items()
            if ae.audio_element_type == m.AUDIO_ELEMENT_OBJECT]


def _rendering_facts(mod: m.IAMFModel) -> list[dict]:
    """One entry per rendering_config that uses anything IAMF v2.0.0 added to
    it: a parameter definition, an element gain offset, a binaural filter
    profile other than the default, or extension bytes that could not be read
    as v2.0.0 syntax. A v1.1.0-style rendering_config adds no entry. Each Mix
    Presentation is listed once, whatever redundant copies the stream holds.

    Values are as coded, except gains (dB); sub_mix counts from 1. JSON
    contract: a defined value is given by name, a reserved or undefined one
    as the bare number."""
    out: list[dict] = []
    seen: set[int] = set()
    for mp in mod.mix_presentations:
        if mp.mix_presentation_id in seen:
            continue
        seen.add(mp.mix_presentation_id)
        for i, sm in enumerate(mp.sub_mixes, start=1):
            for aid, rc in zip(sm.audio_element_ids, sm.rendering_configs):
                if (rc.extension_read and rc.num_parameters in (None, 0)
                        and not rc.element_gain_offset_flag
                        and rc.binaural_filter_profile == 0):
                    continue
                entry: dict = {
                    "mix_presentation_id": mp.mix_presentation_id, "sub_mix": i,
                    "audio_element_id": aid,
                    "headphones_rendering_mode": rc.headphones_rendering_mode,
                    "binaural_filter_profile": m.BINAURAL_FILTER_PROFILE_NAME.get(
                        rc.binaural_filter_profile, rc.binaural_filter_profile),
                }
                if not rc.extension_read:
                    entry["extension_read"] = False
                if rc.position_definitions:
                    entry["position_definitions"] = [
                        {"type": m.PARAM_TYPE_NAME[pd.param_definition_type],
                         "parameter_id": pd.param.parameter_id,
                         "defaults": [dict(zip(
                             _POLAR_AXES if pd.param_definition_type
                             in m.POLAR_PARAM_TYPES else _CARTESIAN_AXES, triple))
                             for triple in pd.defaults]}
                        for pd in rc.position_definitions]
                if rc.other_param_definition_types:
                    entry["other_param_definition_types"] = [
                        m.PARAM_TYPE_NAME.get(t, t)
                        for t in rc.other_param_definition_types]
                g = rc.element_gain_offset
                if g is not None:
                    gain: dict = {"type": m.GAIN_OFFSET_TYPE_NAME.get(
                        g.element_gain_offset_type, g.element_gain_offset_type)}
                    for key, raw in (("element_gain_offset_db", g.element_gain_offset),
                                     ("default_db", g.default_element_gain_offset),
                                     ("min_db", g.min_element_gain_offset),
                                     ("max_db", g.max_element_gain_offset)):
                        if raw is not None:
                            gain[key] = raw / 256.0
                    entry["element_gain_offset"] = gain
                out.append(entry)
    return out


def _declaration_fact(d: m.ParamDeclaration) -> dict:
    out: dict = {"role": d.role}
    if d.mix_presentation_id is not None:
        out["mix_presentation_id"] = d.mix_presentation_id
        out["sub_mix"] = d.sub_mix_index + 1
    if d.audio_element_id is not None:
        out["audio_element_id"] = d.audio_element_id
    if d.layout_index is not None:
        out["layout"] = d.layout_index + 1
    if d.redundant_copy:
        out["redundant_copy"] = True
    return out


def _range(values: list) -> dict | None:
    return {"min": min(values), "max": max(values)} if values else None


def _parameter_facts(mod: m.IAMFModel) -> list[dict]:
    """One entry per parameter_id the stream declares or carries blocks for,
    present only when the stream has Parameter Block OBUs: the definition
    (from its first declaration; every declaration is listed, and
    declarations_differ says whether they agree), then what the blocks that
    were read hold: counts, total duration in ticks, animation types seen
    and the range of the values, by type. Values are as coded, except gains
    (dB) and loudness (LKFS); sub_mix and layout count from 1."""
    if not mod.parameter_blocks:
        return []
    blocks: dict[int, list[m.ParameterBlock]] = {}
    for b in mod.parameter_blocks:
        blocks.setdefault(b.parameter_id, []).append(b)
    out: list[dict] = []
    for pid in list(mod.parameter_definitions) + [p for p in blocks
                                                  if p not in mod.parameter_definitions]:
        decls = mod.parameter_definitions.get(pid, [])
        entry: dict = {"parameter_id": pid, "declared": [_declaration_fact(d) for d in decls]}
        pd = decls[0].param if decls else None
        if pd is not None:
            entry["type"] = m.PARAM_TYPE_NAME.get(pd.param_definition_type,
                                                  pd.param_definition_type)
            entry["parameter_rate"] = pd.parameter_rate
            entry["param_definition_mode"] = pd.param_definition_mode
            if pd.param_definition_mode == 0:
                entry["duration"] = pd.duration
                entry["constant_subblock_duration"] = pd.constant_subblock_duration
                if pd.constant_subblock_duration == 0:
                    entry["subblock_durations"] = list(pd.subblock_durations)
            if pd.default_mix_gain is not None:
                entry["default_mix_gain_db"] = pd.default_mix_gain / 256.0
            if len(decls) > 1:
                entry["declarations_differ"] = any(
                    (d.param.param_definition_type, d.param.parameter_rate,
                     d.param.param_definition_mode, d.param.duration,
                     d.param.constant_subblock_duration, d.param.subblock_durations)
                    != (pd.param_definition_type, pd.parameter_rate,
                        pd.param_definition_mode, pd.duration,
                        pd.constant_subblock_duration, pd.subblock_durations)
                    for d in decls[1:])
        bs = blocks.get(pid, [])
        entry["blocks"] = len(bs)
        unread = [b for b in bs if not b.payload_read]
        if unread:
            entry["blocks_not_read"] = len(unread)
        read = [b for b in bs if b.payload_read]
        if not read:
            out.append(entry)
            continue
        durations = [m.parameter_block_timing(b, pd)[0] for b in read]
        durations = [d for d in durations if d is not None]
        if durations:
            entry["duration_ticks"] = sum(durations)
            entry["block_duration"] = _range(durations)
        entry["subblocks"] = sum(len(b.subblocks) for b in read)
        subblocks = [sb.data for b in read for sb in b.subblocks if sb.data is not None]
        anims = sorted({d.animation_type for d in subblocks if hasattr(d, "animation_type")})
        if anims:
            entry["animation_types"] = [m.ANIMATION_TYPE_NAME.get(a, a) for a in anims]
        ptype = pd.param_definition_type if pd else None
        if ptype == m.PARAM_MIX_GAIN:
            gains = [v / 256.0 for d in subblocks for v in (
                d.gain.start_point_value, d.gain.end_point_value, d.gain.control_point_value)
                if v is not None]
            entry["gain_db"] = _range(gains)
        elif ptype == m.PARAM_DEMIXING:
            entry["dmixp_modes"] = sorted({d.dmixp_mode for d in subblocks})
        elif ptype == m.PARAM_RECON_GAIN:
            gains = [g for d in subblocks for layer in d.layers if layer is not None
                     for g in layer.recon_gains.values()]
            entry["recon_gain"] = _range(gains)
        elif ptype == m.PARAM_MOMENTARY_LOUDNESS:
            entry["momentary_loudness_lkfs"] = _range(
                [-d.momentary_loudness for d in subblocks])
        elif ptype in m.POSITION_PARAM_OBJECTS:
            axes = _POLAR_AXES if ptype in m.POLAR_PARAM_TYPES else _CARTESIAN_AXES
            position: dict = {}
            for i, axis in enumerate(axes):
                values = [v for d in subblocks for obj in d.objects for v in (
                    obj[i].start_point_value, obj[i].end_point_value,
                    obj[i].control_point_value) if v is not None]
                if values:
                    position[axis] = _range(values)
            entry["position"] = position
        out.append(entry)
    return out


def _parameter_lines(params: list[dict]) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for p in params:
        where = "; ".join(
            d["role"] + (f" in mix_presentation {d['mix_presentation_id']}"
                         if "mix_presentation_id" in d else
                         f" of audio_element {d['audio_element_id']}")
            for d in p["declared"]) or "not declared by any descriptor"
        head = f"parameter_id {p['parameter_id']}"
        if "type" in p:
            head += f" {p['type']}"
        parts = [f"{p['blocks']} block" + ("" if p["blocks"] == 1 else "s")]
        if "blocks_not_read" in p:
            parts[-1] += f" ({p['blocks_not_read']} not read)"
        if "duration_ticks" in p:
            parts.append(f"{p['duration_ticks']} ticks at {p['parameter_rate']}/s")
        if "animation_types" in p:
            parts.append(", ".join(p["animation_types"]))
        if p.get("gain_db"):
            parts.append(f"gain {p['gain_db']['min']:+.2f}..{p['gain_db']['max']:+.2f} dB")
        if "dmixp_modes" in p:
            parts.append("dmixp_mode " + ", ".join(str(x) for x in p["dmixp_modes"]))
        if p.get("recon_gain"):
            parts.append(f"recon_gain {p['recon_gain']['min']}..{p['recon_gain']['max']}")
        if p.get("momentary_loudness_lkfs"):
            r = p["momentary_loudness_lkfs"]
            parts.append(f"momentary loudness {r['min']}..{r['max']} LKFS")
        if p.get("position"):
            scale = {"CART8": "/127", "DUAL_CART8": "/127",
                     "CART16": "/32767", "DUAL_CART16": "/32767"}.get(p.get("type"), "")
            parts.append(" ".join(
                f"{axis} {r['min']}..{r['max']}" + ("/127" if axis == "distance" else scale)
                for axis, r in p["position"].items()))
        if p.get("declarations_differ"):
            parts.append("declarations differ")
        lines.append(("parameter", f"{head} ({where}): " + ", ".join(parts)))
    return lines


def _fact_lines(stream: dict) -> list[tuple[str, str]]:
    """(label, text) lines for the object and rendering facts of a summary's
    stream block; empty for a stream that has neither."""
    lines: list[tuple[str, str]] = []
    objects = stream.get("object_elements", [])
    if objects:
        def count(n):
            return ("object count unknown" if n is None
                    else f"{n} object" + ("" if n == 1 else "s"))
        lines.append(("objects", "; ".join(
            f"audio_element {o['audio_element_id']}: {count(o['num_objects'])}"
            for o in objects)))
    for r in stream.get("rendering", []):
        parts: list[str] = []
        for pd in r.get("position_definitions", []):
            scale = {"CART8": "/127", "DUAL_CART8": "/127",
                     "CART16": "/32767", "DUAL_CART16": "/32767"}.get(pd["type"])
            defaults = []
            for d in pd["defaults"]:
                if scale is None:
                    defaults.append(f"azimuth {d['azimuth']} elevation "
                                    f"{d['elevation']} distance {d['distance']}/127")
                else:
                    defaults.append(" ".join(f"{k} {v}{scale}" for k, v in d.items()))
            parts.append(f"{pd['type']} position (parameter {pd['parameter_id']}), "
                         f"default {' | '.join(defaults)}")
        if "other_param_definition_types" in r:
            parts.append("other parameter definition type(s) "
                         + ", ".join(str(t) for t in r["other_param_definition_types"]))
        g = r.get("element_gain_offset")
        if g is not None:
            if g["type"] == "VALUE":
                parts.append(f"element gain offset {g['element_gain_offset_db']:+.2f} dB")
            elif g["type"] == "RANGE":
                parts.append(f"element gain offset {g['default_db']:+.2f} dB by "
                             f"default, adjustable {g['min_db']:+.2f} to "
                             f"{g['max_db']:+.2f} dB about it")
            else:
                parts.append(f"element gain offset of reserved type {g['type']}")
        bfp = r["binaural_filter_profile"]
        if bfp != "AMBIENT":
            parts.append("binaural filter profile "
                         + (bfp if isinstance(bfp, str) else f"reserved ({bfp})"))
        if r.get("extension_read") is False:
            parts.append("extension bytes not read (not IAMF v2.0.0 syntax)")
        lines.append(("rendering", f"mix_presentation {r['mix_presentation_id']} / "
                      f"audio_element {r['audio_element_id']}: " + "; ".join(parts)))
    lines.extend(_parameter_lines(stream.get("parameters", [])))
    return lines


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
        d["stream"] = {
            # JSON contract: the name for a defined profile, the bare value
            # for a reserved one (render_text / render_html label the latter).
            "primary_profile": m.PROFILE_NAME.get(mod.sequence_header.primary_profile,
                                                  mod.sequence_header.primary_profile),
            "codecs": sorted({cc.codec_id for cc in mod.codec_configs.values()}),
            "audio_elements": len(mod.audio_elements),
            "mix_presentations": len(mod.mix_presentations),
            "descriptor_bytes": mod.descriptor_bytes,
            "audio_frames": len(mod.audio_frames),
        }
        # Present only when the stream has object-based elements, or a
        # rendering_config that uses what IAMF v2.0.0 added to it.
        objects, rendering = _object_facts(mod), _rendering_facts(mod)
        if objects:
            d["stream"]["object_elements"] = objects
        if rendering:
            d["stream"]["rendering"] = rendering
        # Present only when the stream carries Parameter Block OBUs.
        parameters = _parameter_facts(mod)
        if parameters:
            d["stream"]["parameters"] = parameters
    return d


def _profile_text(value: str | int) -> str:
    """The summary's primary_profile for a human: a reserved value is said to
    be reserved instead of being printed as a bare number."""
    return value if isinstance(value, str) else m.profile_label(value)


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
        lines.append(f"  stream   : {_profile_text(st['primary_profile'])} profile, "
                     f"codec {','.join(st['codecs'])}, "
                     f"{st['audio_elements']} element(s), {st['mix_presentations']} mix pres, "
                     f"{st['descriptor_bytes']}B descriptor")
        for label, text in _fact_lines(st):
            lines.append(f"  {label:<9}: {text}")
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
    stream_html = facts_html = ""
    if "stream" in s:
        st = s["stream"]
        stream_html = (f"{_profile_text(st['primary_profile'])} profile · "
                       f"codec {', '.join(st['codecs'])} · "
                       f"{st['audio_elements']} element(s) · {st['mix_presentations']} mix pres · "
                       f"{st['descriptor_bytes']}B descriptor")
        facts = [f"{html.escape(label)}: {html.escape(text)}"
                 for label, text in _fact_lines(st)]
        if facts:
            facts_html = f"<div class='meta'>{'<br>'.join(facts)}</div>\n"
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
{facts_html}<div><span class="result">{result}</span></div>
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
