"""L3 loudness checks, descriptor-derived (S-3xx).

These read the loudness metadata carried in the mix presentation — no decoding
required — and catch the FFmpeg 0.0-default (F7), the Dolby-mode stereo-only
loudness layout (F23), missing true peak, and declared clipping (F21). Full
*measured* loudness (render each presentation x layout, BS.1770-4, compare to
declared within tolerance) is Phase 2 and requires the decoder oracle.
"""

from __future__ import annotations
from collections.abc import Iterator, Sequence

from .base import CheckContext, finding
from ..findings import Finding
from ..layouts import LOUDSPEAKER_LAYOUT
from .. import model as m


def _program_native_channels(mod: m.IAMFModel,
                             ae_ids: Sequence[int]) -> int:
    """Max channel count among the referenced audio elements (scene => >2)."""
    best = 0
    for aid in ae_ids:
        ae = mod.audio_elements.get(aid)
        if not ae:
            continue
        if ae.ambisonics is not None:
            best = max(best, ae.ambisonics.output_channel_count)
        for layer in ae.channel_layers:
            cl = LOUDSPEAKER_LAYOUT.get(layer.loudspeaker_layout)
            if cl and cl.channels > 0:
                best = max(best, cl.channels)
    return best


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    for mp in mod.mix_presentations:
        for sm in mp.sub_mixes:
            where0 = f"mix_presentation {mp.mix_presentation_id}"
            labels = [lay.label for lay in sm.layouts]
            native_ch = _program_native_channels(mod, sm.audio_element_ids)

            any_true_peak = False
            for ll in sm.layouts:
                where = f"{where0} / {ll.label}"
                # S-301 unmeasured 0.0 default (F7)
                if ll.integrated_raw == 0 and ll.digital_peak_raw == 0:
                    yield finding(ctx, "S-301",
                                  "loudness is the unmeasured 0.0 default "
                                  "(integrated_loudness=0.0, digital_peak=0.0)",
                                  where=where, expected="measured BS.1770 loudness",
                                  found="0.0 LKFS / 0.0 dBFS")
                # S-304 declared clipping (F21)
                peak = ll.true_peak if ll.true_peak is not None else ll.digital_peak
                if peak is not None and peak >= 0.0:
                    yield finding(ctx, "S-304",
                                  f"declared peak {peak:.2f} dBFS is at/above full scale "
                                  "(clipping hazard)", where=where, found=f"{peak:.2f} dBFS")
                if ll.info_type & 0x1:
                    any_true_peak = True

            # S-302 stereo-only loudness for a multichannel/scene program (F23)
            if native_ch > 2 and set(labels) == {"Stereo"}:
                yield finding(ctx, "S-302",
                              f"program renders {native_ch}-channel/scene content but declares "
                              "loudness for the Stereo layout only — native-layout loudness "
                              "missing (F23)", where=where0,
                              expected="loudness for the native layout", found="Stereo only")

            # S-303 true peak presence (informational)
            if not any_true_peak and sm.layouts:
                yield finding(ctx, "S-303",
                              "no layout advertises true peak (info_type true-peak bit unset)",
                              where=where0)
