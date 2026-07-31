"""Mutation suite — the F4-killer acceptance gate (PRD R2).

Each mutation takes a known-good fixture, corrupts exactly one thing a
descriptor-level validator should catch, and declares which check must fire.
Detection rate and false-pass count are reported. The classes here are the
ones expressible in the descriptor + frame index (topology inconsistency,
dropped/duplicated substreams, ACN violations, dangling refs, truncation,
loudness defaults). The pure essence-misroute F4 (identical descriptor,
scrambled PCM) is out of scope for L1/L2 and belongs to L3 channel-identity.
"""

from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable

from . import build as B


@dataclass
class Mutation:
    label: str
    expect: str            # check_id that must fire
    build_fn: Callable[[], bytes]


def _channel(name):
    return B.channel_spec(name)


def _mut_coupled_wrong():
    s = _channel("7.1.4")
    s.elements[0].layers[0].coupled_substream_count = 4   # should be 5
    return B.build(s)


def _mut_substream_count_wrong():
    s = _channel("5.1")
    s.elements[0].layers[0].substream_count = 3           # should be 4
    return B.build(s)


def _mut_wrong_layout_value():
    # declare 7.1.4 layout but carry a 5.1 topology (4/2) — F4 signature
    s = _channel("5.1")
    s.elements[0].layers[0].loudspeaker_layout = 7        # 7.1.4
    return B.build(s)


def _mut_num_substreams_mismatch():
    s = _channel("stereo")
    s.elements[0].substream_ids = [0, 1]                  # 2 ids, layer says 1
    return B.build(s)


def _mut_drop_substream_frames():
    s = _channel("7.1.4")
    s.drop_frame_substreams = [6]                         # declared, never framed
    return B.build(s)


def _mut_spurious_frame():
    s = _channel("5.1")
    s.extra_frames = [9]                                  # undeclared substream in frames
    return B.build(s)


def _mut_duplicate_substream_id():
    s = _channel("5.1")
    s.elements[0].substream_ids = [0, 0, 2, 3]            # id 0 twice
    return B.build(s)


def _mut_zero_param_rate():
    s = _channel("stereo")
    s.elements[0].params = [(1, 0)]                       # demixing param, rate 0 (F1)
    return B.build(s)


def _mut_dangling_codec_ref():
    s = _channel("stereo")
    s.elements[0].codec_config_id = 99                    # no such codec config
    return B.build(s)


def _mut_dangling_ae_ref():
    s = _channel("stereo")
    s.mixes[0].ae_ids = [777]                             # no such element
    return B.build(s)


def _mut_ambi_mapping_dup():
    s = B.scene_spec(1)
    s.elements[0].ambi_mapping = [0, 1, 1, 3]             # duplicate substream ref
    return B.build(s)


def _mut_ambi_mapping_gap():
    s = B.scene_spec(1)
    s.elements[0].ambi_mapping = [0, 1, 3, 0]             # substream 2 never mapped; 0 duplicated (dup+gap)
    return B.build(s)


def _mut_ambi_non_square():
    s = B.scene_spec(1)
    s.elements[0].ambi_occ_override = 5                   # 5 is not (N+1)^2
    s.elements[0].ambi_mapping = [0, 1, 2, 3, 4]
    s.elements[0].ambi_substream_count = 5
    return B.build(s)


def _mut_truncate():
    s = _channel("7.1.4")
    s.truncate_to = 40                                    # mid-descriptor
    return B.build(s)


def _mut_no_mix_presentation():
    s = _channel("stereo")
    s.mixes = []
    return B.build(s)


def _mut_loudness_zero_default():
    s = _channel("stereo")
    s.mixes[0].layouts[0].integrated_db = 0.0
    s.mixes[0].layouts[0].digital_db = 0.0
    return B.build(s)


def _mut_stereo_only_multichannel():
    s = _channel("7.1.4")
    s.mixes[0].layouts = [B.LayoutSpec(0, -18.0, -6.0)]   # stereo loudness only
    return B.build(s)


def _mut_reserved_layout():
    s = _channel("stereo")
    s.elements[0].layers[0].loudspeaker_layout = 12       # reserved
    return B.build(s)


def _mut_mono_with_coupled():
    s = _channel("mono")
    s.elements[0].layers[0].coupled_substream_count = 1   # mono can't couple
    return B.build(s)


def _mut_clipping_peak():
    s = _channel("stereo")
    s.mixes[0].layouts[0].digital_db = 2.0                # +2 dBFS declared
    return B.build(s)


def _mut_bad_codec():
    s = _channel("stereo")
    s.codec_id = "zzzz"
    return B.build(s)


# -- trim carriage (F31: FFmpeg '-c copy' strips start-trim silently) --------
def _opus_trimmed(**kw):
    s = _channel("stereo")
    s.codec_id = "Opus"                                   # pre_skip 312 in config
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _mut_trim_no_elst():
    from .mp4wrap import wrap_mp4
    return wrap_mp4(B.build(_opus_trimmed(trim_start_first_tu=312)))


def _mut_trim_elst_mismatch():
    from .mp4wrap import wrap_mp4
    return wrap_mp4(B.build(_opus_trimmed(trim_start_first_tu=312)),
                    elst=[(648, 120)])                    # media_time 120 != 312


def _mut_trim_stts_short():
    from .mp4wrap import wrap_mp4
    # end-trim on the OBUs, sample table written as if there were none
    return wrap_mp4(B.build(_opus_trimmed(trim_start_first_tu=312,
                                          trim_end_last_tu=100)),
                    elst=[(860, 312)])


def _mut_trim_fields_stripped():
    # the FFmpeg remux fingerprint: pre_skip > 0, no trimming fields, elst 0
    from .mp4wrap import wrap_mp4
    return wrap_mp4(B.build(_opus_trimmed()), elst=[(960, 0)])


MUTATIONS: list[Mutation] = [
    Mutation("coupled_count_wrong (7.1.4)", "S-201", _mut_coupled_wrong),
    Mutation("substream_count_wrong (5.1)", "S-201", _mut_substream_count_wrong),
    Mutation("wrong_layout_value (5.1 as 7.1.4)", "S-201", _mut_wrong_layout_value),
    Mutation("num_substreams_mismatch", "S-202", _mut_num_substreams_mismatch),
    Mutation("dropped_substream_frames", "S-207", _mut_drop_substream_frames),
    Mutation("spurious_undeclared_frame", "S-207", _mut_spurious_frame),
    Mutation("duplicate_substream_id", "S-205", _mut_duplicate_substream_id),
    Mutation("zero_parameter_rate (F1)", "S-204", _mut_zero_param_rate),
    Mutation("dangling_codec_ref", "S-106", _mut_dangling_codec_ref),
    Mutation("dangling_audio_element_ref", "S-106", _mut_dangling_ae_ref),
    Mutation("ambisonics_mapping_duplicate", "S-203", _mut_ambi_mapping_dup),
    Mutation("ambisonics_mapping_gap", "S-203", _mut_ambi_mapping_gap),
    Mutation("ambisonics_non_square_occ", "S-203", _mut_ambi_non_square),
    Mutation("truncated_stream", "S-108", _mut_truncate),
    Mutation("no_mix_presentation", "S-105", _mut_no_mix_presentation),
    Mutation("loudness_zero_default (F7)", "S-301", _mut_loudness_zero_default),
    Mutation("stereo_only_multichannel (F23)", "S-302", _mut_stereo_only_multichannel),
    Mutation("reserved_loudspeaker_layout", "S-201", _mut_reserved_layout),
    Mutation("mono_with_coupled_substream", "S-201", _mut_mono_with_coupled),
    Mutation("declared_clipping_peak (F21)", "S-304", _mut_clipping_peak),
    Mutation("unknown_codec_id", "S-103", _mut_bad_codec),
    Mutation("trim_without_edit_list (F31)", "S-407", _mut_trim_no_elst),
    Mutation("elst_media_time_mismatch (F31)", "S-407", _mut_trim_elst_mismatch),
    Mutation("stts_ignores_end_trim (F31)", "S-408", _mut_trim_stts_short),
    Mutation("trim_fields_stripped (F31 fingerprint)", "S-409", _mut_trim_fields_stripped),
]


def run_suite(profile: str = "generic"):
    """Return (results, detection_rate). results: list of (label, expect, detected, fired)."""
    from sentinel.engine import validate_bytes
    results = []
    detected = 0
    for mut in MUTATIONS:
        data = mut.build_fn()
        report = validate_bytes(data, source=f"mutation:{mut.label}", profile=profile)
        fired = {f.check_id for f in report.findings}
        ok = mut.expect in fired
        detected += ok
        results.append((mut.label, mut.expect, ok, sorted(fired)))
    return results, detected / len(MUTATIONS)
