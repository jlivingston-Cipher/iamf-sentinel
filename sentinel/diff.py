"""Two-file diff (PRD R7): descriptor structure + rendered PCM.

Descriptor half: profile, codecs, audio element topology, substream ids, and
mix-presentation loudness layouts — proves a remux/re-encode preserved the
*program structure*. Loudness values are compared with a tolerance
(measurement noise is expected; structure is not).

Rendered half (Phase 2, via the decoder oracle): decodes both files to a
common layout and compares the audio itself — per-channel zero-lag
correlation and RMS level delta — proving the *audio* survived. WP1's
decode_verify lineage, generalized to any file pair.
"""

from __future__ import annotations
from typing import Any
from dataclasses import dataclass, field

from . import model as m
from .parser import parse_bytes
from .container.mp4 import parse_mp4
from .engine import detect_container
from .layouts import LOUDSPEAKER_LAYOUT

LOUDNESS_TOL_LU = 0.5


@dataclass
class DiffEntry:
    kind: str            # "STRUCTURAL" | "LOUDNESS" | "RENDER"
    where: str
    a: str
    b: str
    delta: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"kind": self.kind, "where": self.where, "a": self.a, "b": self.b}
        if self.delta is not None:
            d["delta"] = round(self.delta, 3)
        return d


@dataclass
class DiffResult:
    source_a: str
    source_b: str
    entries: list[DiffEntry] = field(default_factory=list)
    render_compared: bool = False
    render_layout: str | None = None
    render_channel_corr: list[float] = field(default_factory=list)
    render_note: str = ""

    @property
    def structural_diffs(self) -> list[DiffEntry]:
        return [e for e in self.entries if e.kind == "STRUCTURAL"]

    @property
    def loudness_diffs(self) -> list[DiffEntry]:
        return [e for e in self.entries if e.kind == "LOUDNESS"]

    @property
    def render_diffs(self) -> list[DiffEntry]:
        return [e for e in self.entries if e.kind == "RENDER"]

    def verdict(self) -> str:
        if self.structural_diffs:
            return "DIFFERENT"
        if self.render_compared and self.render_diffs:
            return "STRUCTURALLY-EQUAL (rendered audio differs)"
        if self.render_compared and not self.render_diffs:
            base = "RENDER-EQUAL"
            return f"{base} (loudness metadata differs)" if self.loudness_diffs else base
        if self.loudness_diffs:
            return "STRUCTURALLY-EQUAL (loudness differs)"
        return "IDENTICAL"

    def exit_code(self) -> int:
        return 1 if (self.structural_diffs or self.render_diffs) else 0


def _load_model(path: str) -> m.IAMFModel:
    with open(path, "rb") as fh:
        data = fh.read()
    if detect_container(data) == "mp4":
        info = parse_mp4(data)
        return parse_bytes(info.descriptor_obus, source=path, container="mp4")
    return parse_bytes(data, source=path, container="raw")


def _element_summary(ae: m.AudioElement) -> str:
    if ae.audio_element_type == m.AUDIO_ELEMENT_CHANNEL and ae.channel_layers:
        top = ae.channel_layers[-1]
        cl = LOUDSPEAKER_LAYOUT.get(top.loudspeaker_layout)
        name = cl.name if cl else f"lsl{top.loudspeaker_layout}"
        return f"channel/{name} sub={ae.num_substreams} coupled={top.coupled_substream_count} ids={ae.audio_substream_ids}"
    if ae.ambisonics:
        a = ae.ambisonics
        return f"scene/ambi order={a.order} occ={a.output_channel_count} sub={ae.num_substreams} ids={ae.audio_substream_ids}"
    return f"type{ae.audio_element_type} sub={ae.num_substreams}"


RENDER_CORR_GATE = 0.98
RENDER_LEVEL_GATE_DB = 0.5


def render_compare(res: DiffResult, path_a: str, path_b: str,
                   toolchain: Any,
                   layout: str | None = None) -> None:
    """Rendered-PCM half of R7: decode both files, compare per-channel."""
    try:
        import numpy as np
        from sentinel_pro import dsp
        from sentinel_pro.l3_rendered import CHANNEL_NAMES, _native_analysis_layout
    except ImportError:
        res.render_note = "rendered comparison requires iamf-sentinel-pro (+ numpy)"
        return

    if layout is None:
        ma, mb = _load_model(path_a), _load_model(path_b)
        la, _ = _native_analysis_layout(ma, [aid for mp in ma.mix_presentations
                                             for sm in mp.sub_mixes
                                             for aid in sm.audio_element_ids])
        lb, _ = _native_analysis_layout(mb, [aid for mp in mb.mix_presentations
                                             for sm in mp.sub_mixes
                                             for aid in sm.audio_element_ids])
        layout = la if la == lb and la is not None else "2.0"

    decoder = toolchain.oracles()[0] if toolchain.available else None
    if decoder is None:
        res.render_note = "no decoder oracle available"
        return
    da = toolchain.decode(toolchain.prepare_input(path_a), layout, decoder)
    db = toolchain.decode(toolchain.prepare_input(path_b), layout, decoder)
    if not (da.ok and db.ok):
        which = [p for p, d in ((path_a, da), (path_b, db)) if not d.ok]
        res.entries.append(DiffEntry("RENDER", f"decode @ {layout}",
                                     "ok" if da.ok else "FAILED",
                                     "ok" if db.ok else "FAILED"))
        res.render_compared = True
        res.render_layout = layout
        res.render_note = f"decode failed for {', '.join(which)}"
        return

    _sa, pa = dsp.read_wav(da.wav_path)
    _sb, pb = dsp.read_wav(db.wav_path)
    res.render_compared = True
    res.render_layout = layout
    if pa.shape[1] != pb.shape[1]:
        res.entries.append(DiffEntry("RENDER", f"channels @ {layout}",
                                     str(pa.shape[1]), str(pb.shape[1])))
        return
    n = min(pa.shape[0], pb.shape[0])
    pa, pb = pa[:n], pb[:n]
    names = CHANNEL_NAMES.get(layout, [str(i) for i in range(pa.shape[1])])
    for ch in range(pa.shape[1]):
        xa, xb = pa[:, ch], pb[:, ch]
        ra = float(np.sqrt((xa * xa).mean()))
        rb = float(np.sqrt((xb * xb).mean()))
        silent_a, silent_b = ra < 1e-6, rb < 1e-6
        if silent_a and silent_b:
            res.render_channel_corr.append(1.0)
            continue
        if silent_a != silent_b:
            res.render_channel_corr.append(0.0)
            res.entries.append(DiffEntry(
                "RENDER", f"{names[ch]} @ {layout}",
                "silent" if silent_a else f"{20*np.log10(max(ra,1e-9)):.1f} dBFS",
                "silent" if silent_b else f"{20*np.log10(max(rb,1e-9)):.1f} dBFS"))
            continue
        num = float((xa * xb).sum())
        den = float(np.sqrt((xa * xa).sum() * (xb * xb).sum()))
        corr = num / den if den > 0 else 0.0
        res.render_channel_corr.append(corr)
        level_delta = 20.0 * (np.log10(max(rb, 1e-9)) - np.log10(max(ra, 1e-9)))
        if corr < RENDER_CORR_GATE or abs(level_delta) > RENDER_LEVEL_GATE_DB:
            res.entries.append(DiffEntry(
                "RENDER", f"{names[ch]} @ {layout}",
                f"r={corr:.4f}", f"ΔRMS={level_delta:+.2f} dB",
                delta=float(level_delta)))


def diff_files(path_a: str, path_b: str, *, toolchain: Any = None,
               render_layout: str | None = None) -> DiffResult:
    ma, mb = _load_model(path_a), _load_model(path_b)
    res = DiffResult(path_a, path_b)

    # profile
    pa = ma.sequence_header, mb.sequence_header
    if pa[0] and pa[1]:
        for role in ("primary_profile", "additional_profile"):
            va, vb = getattr(pa[0], role), getattr(pa[1], role)
            if va != vb:
                res.entries.append(DiffEntry("STRUCTURAL", role,
                                             m.PROFILE_NAME.get(va, va), m.PROFILE_NAME.get(vb, vb)))

    # codecs (by codec_id set)
    ca = {cc.codec_id for cc in ma.codec_configs.values()}
    cb = {cc.codec_id for cc in mb.codec_configs.values()}
    if ca != cb:
        res.entries.append(DiffEntry("STRUCTURAL", "codecs", str(sorted(ca)), str(sorted(cb))))

    # audio elements (aligned by sorted id order — topology is what matters)
    ea = [_element_summary(ae) for _, ae in sorted(ma.audio_elements.items())]
    eb = [_element_summary(ae) for _, ae in sorted(mb.audio_elements.items())]
    if ea != eb:
        for i in range(max(len(ea), len(eb))):
            sa = ea[i] if i < len(ea) else "(absent)"
            sb = eb[i] if i < len(eb) else "(absent)"
            if sa != sb:
                res.entries.append(DiffEntry("STRUCTURAL", f"audio_element[{i}]", sa, sb))

    # mix presentation loudness layouts (aligned by index)
    la = _loudness_index(ma)
    lb = _loudness_index(mb)
    labels = sorted(set(la) | set(lb))
    for label in labels:
        va, vb = la.get(label), lb.get(label)
        if va is None or vb is None:
            res.entries.append(DiffEntry("STRUCTURAL", f"loudness layout {label}",
                                         "present" if va is not None else "absent",
                                         "present" if vb is not None else "absent"))
            continue
        if abs(va - vb) > LOUDNESS_TOL_LU:
            res.entries.append(DiffEntry("LOUDNESS", f"integrated @ {label}",
                                         f"{va:.2f} LKFS", f"{vb:.2f} LKFS",
                                         delta=vb - va))

    if toolchain is not None:
        try:
            render_compare(res, path_a, path_b, toolchain, layout=render_layout)
        finally:
            toolchain.cleanup()
    return res


def _loudness_index(mod: m.IAMFModel) -> dict[str, float]:
    out = {}
    for mp in mod.mix_presentations:
        for sm in mp.sub_mixes:
            for ll in sm.layouts:
                out[ll.label] = ll.integrated_loudness
    return out


def render_diff_text(res: DiffResult) -> str:
    lines = ["Sentinel diff", f"  a: {res.source_a}", f"  b: {res.source_b}",
             f"  verdict: {res.verdict()}", ""]
    if not res.entries:
        lines.append("  descriptor structure and loudness identical.")
    for e in res.entries:
        d = f"  (Δ {e.delta:+.2f})" if e.delta is not None else ""
        lines.append(f"  [{e.kind}] {e.where}: a={e.a}  b={e.b}{d}")
    if res.render_compared:
        corr = ", ".join(f"{c:.4f}" for c in res.render_channel_corr)
        lines.append("")
        lines.append(f"  rendered @ {res.render_layout}: per-channel corr [{corr}]"
                     + (f"  note: {res.render_note}" if res.render_note else ""))
    lines.append("")
    lines.append(f"exit code: {res.exit_code()}")
    return "\n".join(lines)
