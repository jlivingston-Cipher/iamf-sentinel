"""Container / profile checks (S-4xx) for IAMF-in-MP4."""

from __future__ import annotations
from collections.abc import Iterator, Sequence

from .base import CheckContext, finding
from ..container.mp4 import MP4Info
from ..findings import Finding
from .. import model as m


def rfc6381_codec_string(mod: m.IAMFModel) -> str | None:
    """Derive the canonical iamf.PPP.AAA.<fourcc> codecs string from the descriptor.

    The 4CC is used verbatim, so the canonical form for Opus is
    'iamf.001.001.Opus' (capital O) — the F12 case-normalisation reference.
    """
    sh = mod.sequence_header
    if sh is None:
        return None
    codec = next(iter(mod.codec_configs.values()), None)
    if codec is None:
        return None
    return f"iamf.{sh.primary_profile:03d}.{sh.additional_profile:03d}.{codec.codec_id}"


def _trim_stats(frames: Sequence) -> tuple[int, int, int] | None:
    """Per-substream trim bookkeeping -> (start_trim, end_trim, temporal_units).

    Substreams of one element must agree on trimming; we take the per-substream
    sums and report the max (a disagreement surfaces as an S-407 mismatch).
    """
    per: dict[int, list[int]] = {}
    for fr in frames:
        st = per.setdefault(fr.substream_id, [0, 0, 0])
        st[0] += fr.trim_start
        st[1] += fr.trim_end
        st[2] += 1
    if not per:
        return None
    return (max(v[0] for v in per.values()),
            max(v[1] for v in per.values()),
            max(v[2] for v in per.values()))


def _media_units(samples: int, timescale: int | None, sample_rate: int | None) -> int:
    """Convert a codec-sample count into media-timescale units (usually 1:1)."""
    if timescale and sample_rate and timescale != sample_rate:
        return round(samples * timescale / sample_rate)
    return samples


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    """X-76a shape: one helper per check family, yielded in the pre-split
    order — S-409 first (it runs raw or MP4), then the MP4-only checks."""
    info = ctx.mp4
    yield from _trim_checks(mod, ctx)
    if info is None:
        return
    yield from _check_sample_entry(ctx, info)
    yield from _check_brand(ctx, info)
    yield from _check_fast_start(ctx, info)
    yield from _check_codec_string(mod, ctx)
    yield from _check_stts_sanity(ctx, info)
    yield from _check_trim_tables(mod, ctx, info)
    yield from _check_av_duration(ctx, info)


def _check_sample_entry(ctx: CheckContext, info: MP4Info) -> Iterator[Finding]:
    """S-404 iamf sample entry."""
    if not info.has_iamf_sample_entry:
        yield finding(ctx, "S-404", "no 'iamf' sample entry found in the MP4")


def _check_brand(ctx: CheckContext, info: MP4Info) -> Iterator[Finding]:
    """S-401 iamf brand present."""
    if "iamf" not in info.compatible_brands and info.major_brand != "iamf":
        yield finding(ctx, "S-401",
                      "MP4 compatible_brands does not include 'iamf'",
                      expected="'iamf' in compatible_brands",
                      found=str(info.compatible_brands))


def _check_fast_start(ctx: CheckContext, info: MP4Info) -> Iterator[Finding]:
    """S-402 fast-start (moov before mdat)."""
    order = info.top_level_order
    if "moov" in order and "mdat" in order:
        if order.index("moov") > order.index("mdat"):
            yield finding(ctx, "S-402",
                          "moov box follows mdat (not fast-start; ingest/progressive "
                          "playback may stall)", expected="moov before mdat",
                          found=" ".join(order))


def _check_codec_string(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    """S-403 RFC6381 codec string casing (F12)."""
    canonical = rfc6381_codec_string(mod)
    if canonical is not None:
        lowered = canonical.lower()
        if canonical != lowered:
            yield finding(ctx, "S-403",
                          f"canonical codecs string is {canonical!r}; verify downstream "
                          f"manifests do not lowercase the 4CC (F12: GPAC emits {lowered!r} "
                          "vs YouTube's expected mixed case)",
                          expected=canonical, found=f"{lowered} (if lowercased)")


def _check_stts_sanity(ctx: CheckContext, info: MP4Info) -> Iterator[Finding]:
    """S-405 stts/ctts timing sanity (R4 depth, F9)."""
    for tr in info.tracks:
        if tr.handler != "soun" or not tr.stts:
            continue
        zero_runs = [(i, c) for i, (c, d) in enumerate(tr.stts) if d == 0]
        if zero_runs:
            yield finding(ctx, "S-405",
                          f"audio stts contains {len(zero_runs)} zero-duration entr"
                          f"{'y' if len(zero_runs) == 1 else 'ies'} "
                          f"(first at entry {zero_runs[0][0]}) — F9 DTS-patch residue or "
                          "timing corruption", where="trak(soun)/stbl/stts",
                          found=f"entries {[i for i, _ in zero_runs[:5]]}")
        if tr.timescale and tr.duration is not None:
            stts_total = sum(c * d for c, d in tr.stts)
            drift = abs(stts_total - tr.duration) / tr.timescale
            if drift > 0.05:
                yield finding(ctx, "S-405",
                              f"audio stts total ({stts_total / tr.timescale:.3f} s) does not "
                              f"match mdhd duration ({tr.duration / tr.timescale:.3f} s)",
                              where="trak(soun)/stbl/stts",
                              expected=f"{tr.duration / tr.timescale:.3f} s",
                              found=f"{stts_total / tr.timescale:.3f} s")


def _check_trim_tables(mod: m.IAMFModel, ctx: CheckContext,
                       info: MP4Info) -> Iterator[Finding]:
    """S-407/S-408 trim carriage vs container tables (F31/§6.2.2)."""
    track = next((t for t in info.tracks if t.has_iamf), None)
    stats = _trim_stats(info.frame_refs)
    cc = next(iter(mod.codec_configs.values()), None)
    if track is not None and stats is not None:
        start_trim, end_trim, tus = stats
        sr = cc.sample_rate if cc else None

        # S-407: OBUs carry start-trim -> edts/elst SHALL be present and agree
        media_times = [mt for _seg, mt, _rate in track.elst_entries if mt >= 0]
        if start_trim > 0 and not media_times:
            yield finding(ctx, "S-407",
                          "audio frames carry num_samples_to_trim_at_start but the "
                          "track has no edts/elst (IAMF v1.1.0 §6.2.2: the edts and "
                          "elst boxes SHALL be present to reflect the trimming status)",
                          where="trak(iamf)",
                          expected=f"elst media_time == {start_trim}",
                          found="edts absent" if not track.edts_present
                                else "edts present, no usable elst entry")
        elif media_times:
            expected_mt = _media_units(start_trim, track.timescale, sr)
            if media_times[0] != expected_mt:
                yield finding(ctx, "S-407",
                              f"elst media_time ({media_times[0]}) does not equal the "
                              f"summed OBU start-trim ({start_trim} samples)",
                              where="trak(iamf)/edts/elst",
                              expected=str(expected_mt), found=str(media_times[0]))

        # S-408: total stts duration vs the §6.2.2 duration model
        if track.stts and cc and cc.num_samples_per_frame:
            stts_total = sum(c * d for c, d in track.stts)
            expected = _media_units(tus * cc.num_samples_per_frame - end_trim,
                                    track.timescale, sr)
            if stts_total != expected:
                yield finding(ctx, "S-408",
                              f"total stts duration ({stts_total}) != temporal units x "
                              f"num_samples_per_frame - end-trim ({tus} x "
                              f"{cc.num_samples_per_frame} - {end_trim} = {expected}); "
                              "sample durations do not reflect the trimming status "
                              "(§6.2.2 model: start-trim included, end-trim excluded)",
                              where="trak(iamf)/stbl/stts",
                              expected=str(expected), found=str(stts_total))


def _check_av_duration(ctx: CheckContext, info: MP4Info) -> Iterator[Finding]:
    """S-406 A/V duration coherence (R4)."""
    if info.video_present:
        adur = [t.duration_s for t in info.tracks if t.handler == "soun" and t.duration_s]
        vdur = [t.duration_s for t in info.tracks if t.handler == "vide" and t.duration_s]
        if adur and vdur and abs(adur[0] - vdur[0]) > 0.25:
            yield finding(ctx, "S-406",
                          f"audio ({adur[0]:.2f} s) and video ({vdur[0]:.2f} s) track "
                          f"durations differ by {abs(adur[0] - vdur[0]):.2f} s",
                          expected="|Δ| <= 0.25 s",
                          found=f"Δ = {abs(adur[0] - vdur[0]):.2f} s")


def _trim_checks(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    """S-409: codec-delay samples never trimmed (raw or MP4 — the F31 fingerprint)."""
    frames = ctx.mp4.frame_refs if ctx.mp4 is not None else mod.audio_frames
    stats = _trim_stats(frames)
    if stats is None:
        return
    start_trim, _end_trim, _tus = stats
    cc = next(iter(mod.codec_configs.values()), None)
    if cc is None or cc.codec_id != "Opus":
        return
    pre_skip = cc.opus_pre_skip or 0
    if pre_skip > 0 and start_trim == 0:
        yield finding(ctx, "S-409",
                      f"Opus pre_skip is {pre_skip} but no audio frame carries "
                      "num_samples_to_trim_at_start — the decoder-delay samples ship "
                      "as content (FFmpeg '-c copy' strips the trim fields silently; "
                      "F31). Downstream OBU-honouring decoders will emit "
                      f"{pre_skip} extra samples",
                      where="audio frames",
                      expected=f"summed trim_at_start >= pre_skip ({pre_skip})",
                      found="no trimming fields on any audio frame")
