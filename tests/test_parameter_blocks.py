"""The parameter-definition registry and the Parameter Block OBU reader
(IA-0051 stage 1): what the stream declares about its parameters, and what
its blocks say, read and recorded — not judged.

Two things are pinned. The registry: every parameter_id a descriptor
declares, where (Audio Element demixing / recon gain, Mix Presentation
element and output mix gains, RenderingConfig position definitions, the
momentary-loudness definition of a LoudnessInfo), with every field of the
definition, and the fact of an id declared more than once. The reader:
Parameter Block payloads decoded by the first declaration of their id —
block-level durations in mode 1, each subblock's data by type (mix gain with
its five animation types, demixing, recon gain by layer, the six position
types bit-packed, momentary loudness) — in raw streams and in MP4 samples.

Stage 1 adds no finding. A payload that cannot be read (no declaration, an
undefined animation type, truncation, an overrunning subblock count) leaves
the block in the model with payload_read False and a parse note, never a
parse error, so S-108 does not move; every such case here also asserts that
no exception escapes and the report is still produced. A test that has only
ever passed proves nothing: each reader branch here was shown to fail with
that branch broken (the IA-0051 switch-off table).

Citations (``v2:`` IAMF v2.0.0 index.bs at 4d2c6da, by line) are beside the
code in sentinel/parser.py and sentinel/model.py. All bytes are synthesised
by fixtures/ — no reference vectors are involved.
"""

from __future__ import annotations

import json

import pytest

from fixtures import build as B
from fixtures.mp4wrap import wrap_mp4
from sentinel import model as m
from sentinel.engine import validate_bytes
from sentinel.parser import parse_bytes
from sentinel.report import render_html, render_json, render_text

STEP, LINEAR, BEZIER, INTER_LINEAR, INTER_BEZIER = 0, 1, 2, 3, 4
POLAR, CART8, CART16, DUAL_POLAR, DUAL_CART8, DUAL_CART16 = 3, 4, 5, 6, 7, 8
Q = B.q78


def report(data: bytes):
    r = validate_bytes(data)
    assert r.execution_error is None, r.execution_error
    return r


def no_findings_moved(r) -> None:
    """Stage 1 adds no finding: nothing about parameter blocks reaches S-108
    or any other check."""
    assert r.model.parse_errors == []
    assert not any("parameter" in f.message.lower() and "block" in f.message.lower()
                   for f in r.findings)


def block_notes(r) -> list[str]:
    return [n for n in r.model.parse_notes if n.startswith("parameter block")]


def decl(r, pid: int, index: int = 0) -> m.ParamDeclaration:
    return r.model.parameter_definitions[pid][index]


def stereo_with(blocks: list[B.ParameterBlockSpec], *, element_gain=None, output_gain=None,
                temporal_units: int = 2, **kw) -> B.IAMFSpec:
    """A stereo stream whose mix gains are declared as given (mode-1 ids 100
    and 101 by default) and which carries the blocks."""
    spec = B.channel_spec("stereo")
    mx = spec.mixes[0]
    mx.element_mix_gains = {300: element_gain or B.ParamDefSpec(0, parameter_id=100)}
    mx.output_mix_gain = output_gain or B.ParamDefSpec(0, parameter_id=101)
    spec.temporal_units = temporal_units
    spec.parameter_blocks = blocks
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def one_block(data: bytes, **kw) -> B.IAMFSpec:
    """A stereo stream with a single mode-1 block of parameter_id 100 holding
    one subblock of `data`, covering one 480-sample frame."""
    kw.setdefault("mode1", (480, 480))
    return stereo_with([B.ParameterBlockSpec(100, 0, subblocks=[B.SubblockSpec(data)], **kw)])


def the_block(r, index: int = 0) -> m.ParameterBlock:
    return r.model.parameter_blocks[index]


# =================================================================== registry
def test_mix_presentation_gains_are_declared_with_every_field():
    spec = stereo_with([], element_gain=B.ParamDefSpec(
        0, parameter_id=100, rate=24000, default_mix_gain=Q(-3.0), reserved=0x55),
        output_gain=B.ParamDefSpec(0, parameter_id=101, mode=0, duration=960,
                                   constant_subblock_duration=240, default_mix_gain=Q(1.5)))
    r = report(B.build(spec))
    e, o = decl(r, 100), decl(r, 101)
    assert (e.role, e.mix_presentation_id, e.sub_mix_index, e.audio_element_id) == (
        "element_mix_gain", 42, 0, 300)
    assert (e.param.param_definition_type, e.param.parameter_rate,
            e.param.param_definition_mode, e.param.reserved, e.param.default_mix_gain) == (
        0, 24000, 1, 0x55, Q(-3.0))
    assert e.param.duration is None and e.param.constant_subblock_duration is None
    assert (o.role, o.mix_presentation_id, o.sub_mix_index, o.audio_element_id) == (
        "output_mix_gain", 42, 0, None)
    assert (o.param.param_definition_mode, o.param.duration,
            o.param.constant_subblock_duration, o.param.num_subblocks,
            o.param.default_mix_gain) == (0, 960, 240, None, Q(1.5))
    sm = r.model.mix_presentations[0].sub_mixes[0]
    assert sm.element_mix_gains == [e.param] and sm.output_mix_gain is o.param
    assert e.file_offset == r.model.mix_presentations[0].header.file_offset
    assert not e.redundant_copy
    no_findings_moved(r)


def test_definition_with_explicit_subblock_durations_is_read():
    spec = stereo_with([], output_gain=B.ParamDefSpec(
        0, parameter_id=101, mode=0, duration=480, constant_subblock_duration=0,
        subblock_durations=[100, 200, 180]))
    pd = decl(report(B.build(spec)), 101).param
    assert (pd.duration, pd.constant_subblock_duration, pd.num_subblocks,
            pd.subblock_durations) == (480, 0, 3, [100, 200, 180])


def test_audio_element_demixing_and_recon_gain_are_declared():
    spec = B.channel_spec("5.1")
    spec.elements[0].params = [
        B.ParamDefSpec(1, parameter_id=200, mode=0, duration=480, constant_subblock_duration=480,
                       default_dmixp_mode=5, default_w=7),
        B.ParamDefSpec(2, parameter_id=201, mode=0, duration=480, constant_subblock_duration=480)]
    r = report(B.build(spec))
    d, g = decl(r, 200), decl(r, 201)
    assert (d.role, d.audio_element_id, d.mix_presentation_id) == ("demixing", 300, None)
    assert (d.param.param_definition_type, d.param.default_dmixp_mode, d.param.default_w) == (
        1, 5, 7)
    assert (g.role, g.audio_element_id, g.param.param_definition_type) == ("recon_gain", 300, 2)
    assert g.param.default_dmixp_mode is None and g.param.default_mix_gain is None
    assert r.model.audio_elements[300].parameters == [d.param, g.param]
    assert r.model.audio_elements[300].other_param_definition_types == []
    no_findings_moved(r)


@pytest.mark.parametrize("ptype", [0, 3, 9, 10, 300])
def test_audio_element_other_definition_types_are_recorded(ptype):
    # Read as param_definition_size + bytes, as the base tree did; the type
    # is now on record. v2.0.0 gives this form to types above 9 only.
    spec = B.channel_spec("stereo")
    spec.elements[0].raw_config = None
    w = B.Writer().leb128(spec.elements[0].id).u8(0).leb128(0).leb128(2).leb128(0).leb128(1)
    w.leb128(1).leb128(ptype).leb128(3).raw(b"\x01\x02\x03")        # one skipped definition
    w.u8(1 << 5).u8(1 << 4).u8(1).u8(1)                              # the stereo layer
    ae_obu = B.obu(1, w.bytes())
    data = B.build(spec)
    r = report(data.replace(B._audio_element(spec.elements[0]), ae_obu))
    ae = r.model.audio_elements[300]
    assert (ae.num_parameters, ae.parameters, ae.other_param_definition_types) == (1, [], [ptype])
    assert ae.channel_layers[0].loudspeaker_layout == 1
    assert ptype not in r.model.parameter_definitions


def test_position_definitions_are_declared_from_the_rendering_config():
    spec = B.object_spec(dual=True)
    r = report(B.build(spec))
    p = decl(r, 2000)
    assert (p.role, p.audio_element_id, p.mix_presentation_id, p.sub_mix_index) == (
        "position", 300, 42, 0)
    assert p.param.param_definition_type == DUAL_POLAR and p.param.param_definition_mode == 1
    assert p.param is r.model.mix_presentations[0].sub_mixes[0].rendering_configs[0] \
        .position_definitions[0].param


def test_unreadable_rendering_extension_declares_nothing():
    spec = B.object_spec()
    spec.mixes[0].rendering[300].raw_extension = b"\x01\x03\x07"       # not v2.0.0 syntax
    r = validate_bytes(B.build(spec))
    assert 2000 not in r.model.parameter_definitions
    assert sorted(r.model.parameter_definitions) == [1000]


def test_momentary_loudness_definition_is_declared_from_loudness_info():
    spec = B.channel_spec("stereo")
    spec.mixes[0].layouts[0].true_peak_db = -5.0
    spec.mixes[0].layouts[0].live = True
    spec.mixes[0].layouts[0].momentary = B.MomentarySpec(
        B.ParamDefSpec(9, parameter_id=127, mode=0, duration=1024,
                       constant_subblock_duration=1024),
        num_bin_pairs_minus_one=5, bin_width_minus_one=22, first_bin_center=41,
        counts=[24, 0, 7, 1, 300, 2, 0, 0, 1, 1, 9, 128], reserved=1)
    spec.mixes[0].layouts[0].loudness_range = 9
    spec.mixes[0].layouts[0].info_type_bytes = b"\xaa\xbb"
    r = report(B.build(spec))
    d = decl(r, 127)
    assert (d.role, d.mix_presentation_id, d.sub_mix_index, d.layout_index,
            d.audio_element_id) == ("momentary_loudness", 42, 0, 0, None)
    assert (d.param.param_definition_type, d.param.duration,
            d.param.constant_subblock_duration) == (9, 1024, 1024)
    ll = r.model.mix_presentations[0].sub_mixes[0].layouts[0]
    assert ll.info_type == 1 | 4 | 8 | 16
    ml = ll.momentary_loudness
    assert (ml.param, ml.num_bin_pairs_minus_one, ml.bin_width_minus_one, ml.first_bin_center,
            ml.reserved, ml.counts) == (d.param, 5, 22, 41, 1,
                                        [24, 0, 7, 1, 300, 2, 0, 0, 1, 1, 9, 128])
    assert (ll.loudness_range, ll.info_type_bytes, ll.info_type_read) == (9, 2, True)
    # the layout after it is still found where it was
    assert len(r.model.mix_presentations[0].sub_mixes[0].layouts) == len(spec.mixes[0].layouts)
    assert ll.integrated_loudness == -18.0 and ll.true_peak == -5.0
    no_findings_moved(r)


def test_loudness_info_envelope_without_its_syntax_is_skipped_and_noted():
    spec = B.channel_spec("5.1")                     # two layouts: the second must still read
    ly = spec.mixes[0].layouts[0]
    ly.momentary = B.MomentarySpec(B.ParamDefSpec(9, parameter_id=127))
    ly.info_type_raw = b"\x7f\x80"             # bit 3 set, two bytes: no definition fits
    r = report(B.build(spec))
    ll = r.model.mix_presentations[0].sub_mixes[0].layouts[0]
    assert (ll.info_type_size, ll.info_type_read, ll.momentary_loudness,
            ll.loudness_range) == (2, False, None, None)
    assert 127 not in r.model.parameter_definitions
    (note,) = [n for n in r.model.parse_notes if n.startswith("loudness_info")]
    assert "announces syntax its 2-byte envelope does not hold" in note
    assert r.model.parse_errors == []
    assert ll.integrated_loudness == -18.0 and r.model.mix_presentations[0].sub_mixes[0] \
        .layouts[1].integrated_loudness == -20.0 and r.model.audio_frames


def test_loudness_info_envelope_cut_after_the_definition_keeps_none_of_it():
    # momentary loudness reads whole, the loudness_range byte bit 4 announces
    # is missing: the envelope is skipped as one, and nothing of it is kept
    spec = B.channel_spec("stereo")
    ly = spec.mixes[0].layouts[0]
    ly.momentary = B.MomentarySpec(B.ParamDefSpec(9, parameter_id=127, mode=0, duration=480,
                                                  constant_subblock_duration=480))
    ly.loudness_range = 3
    env = B.Writer()
    ly.momentary.definition.write(env, with_type=False)
    env.u16(0)
    env.leb128(0).leb128(0)
    ly.info_type_raw = env.bytes()                       # bit 4 set, no byte for it
    r = report(B.build(spec))
    ll = r.model.mix_presentations[0].sub_mixes[0].layouts[0]
    assert ll.info_type & 16 and not ll.info_type_read
    assert (ll.momentary_loudness, ll.loudness_range) == (None, None)
    assert 127 not in r.model.parameter_definitions
    assert len([n for n in r.model.parse_notes if n.startswith("loudness_info")]) == 1


def test_loudness_info_live_bit_alone_reads_an_empty_envelope():
    spec = B.channel_spec("stereo")
    spec.mixes[0].layouts[0].live = True
    ll = report(B.build(spec)).model.mix_presentations[0].sub_mixes[0].layouts[0]
    assert (ll.info_type, ll.info_type_size, ll.info_type_bytes, ll.info_type_read) == (
        4, 0, 0, True)


def test_an_id_declared_twice_is_recorded_twice():
    # identical declarations in two sub-mix roles, and a conflicting one
    spec = stereo_with([], element_gain=B.ParamDefSpec(0, parameter_id=100),
                       output_gain=B.ParamDefSpec(0, parameter_id=100, rate=24000, mode=0,
                                                  duration=1, constant_subblock_duration=1))
    r = report(B.build(spec))
    decls = r.model.parameter_definitions[100]
    assert [d.role for d in decls] == ["element_mix_gain", "output_mix_gain"]
    assert [d.param.parameter_rate for d in decls] == [48000, 24000]
    assert len(r.model.parameter_definitions) == 1
    no_findings_moved(r)


def test_redundant_descriptor_copies_declare_again_and_say_so():
    spec = stereo_with([])
    raw = B.build(spec)
    mp = B._mix_presentation(spec.mixes[0])
    copy = bytes([mp[0] | 0x04]) + mp[1:]                        # obu_redundant_copy
    r = report(raw.replace(mp, mp + copy))
    decls = r.model.parameter_definitions[100]
    assert [d.redundant_copy for d in decls] == [False, True]
    assert decls[0].param == decls[1].param


# ============================================================ blocks: timing
def test_mode_1_block_fields_and_implied_subblock_count():
    r = report(B.build(one_block(B.mix_gain_data(STEP, Q(-6.0)), mode1=(480, 480))))
    b = the_block(r)
    assert (b.parameter_id, b.param_definition_type, b.param_definition_mode) == (100, 0, 1)
    assert (b.duration, b.constant_subblock_duration, b.num_subblocks) == (480, 480, None)
    assert b.payload_read and b.read_error is None and b.extra_bytes == 0
    assert [sb.subblock_duration for sb in b.subblocks] == [None]
    assert m.parameter_block_timing(b, decl(r, 100).param) == (480, [480])
    assert b.header.file_offset > 0 and r.model.parameter_block_ids == [100]
    no_findings_moved(r)


def test_mode_1_constant_subblock_duration_splits_with_a_short_last_subblock():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 200), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, Q(-1.0))),
        B.SubblockSpec(B.mix_gain_data(STEP, Q(-2.0))),
        B.SubblockSpec(B.mix_gain_data(STEP, Q(-3.0)))])])
    r = report(B.build(spec))
    b = the_block(r)
    assert m.implied_num_subblocks(480, 200) == 3
    assert [sb.data.gain.start_point_value for sb in b.subblocks] == [Q(-1.0), Q(-2.0), Q(-3.0)]
    assert m.parameter_block_timing(b, decl(r, 100).param) == (480, [200, 200, 80])


def test_mode_1_explicit_subblock_durations_are_read_per_subblock():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 0), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, Q(-1.0)), duration=100),
        B.SubblockSpec(B.mix_gain_data(STEP, Q(-2.0)), duration=380)])])
    r = report(B.build(spec))
    b = the_block(r)
    assert (b.duration, b.constant_subblock_duration, b.num_subblocks) == (480, 0, 2)
    assert [sb.subblock_duration for sb in b.subblocks] == [100, 380]
    assert m.parameter_block_timing(b, decl(r, 100).param) == (480, [100, 380])


def test_mode_0_block_carries_no_timing_and_takes_the_definitions():
    spec = stereo_with(
        [B.ParameterBlockSpec(101, 0, subblocks=[
            B.SubblockSpec(B.mix_gain_data(STEP, Q(-1.0))),
            B.SubblockSpec(B.mix_gain_data(STEP, Q(-2.0))),
            B.SubblockSpec(B.mix_gain_data(STEP, Q(-3.0)))])],
        output_gain=B.ParamDefSpec(0, parameter_id=101, mode=0, duration=480,
                                   constant_subblock_duration=0,
                                   subblock_durations=[100, 200, 180]))
    r = report(B.build(spec))
    b = the_block(r)
    assert (b.param_definition_mode, b.duration, b.constant_subblock_duration,
            b.num_subblocks) == (0, None, None, None)
    assert [sb.subblock_duration for sb in b.subblocks] == [None, None, None]
    assert m.parameter_block_timing(b, decl(r, 101).param) == (480, [100, 200, 180])
    assert m.parameter_block_timing(b, None) == (None, [])


def test_mode_0_constant_subblock_duration_implies_the_count():
    spec = stereo_with(
        [B.ParameterBlockSpec(101, 0, subblocks=[
            B.SubblockSpec(B.mix_gain_data(STEP, Q(-1.0))),
            B.SubblockSpec(B.mix_gain_data(STEP, Q(-2.0)))])],
        output_gain=B.ParamDefSpec(0, parameter_id=101, mode=0, duration=480,
                                   constant_subblock_duration=240))
    r = report(B.build(spec))
    assert len(the_block(r).subblocks) == 2 and the_block(r).payload_read
    assert m.parameter_block_timing(the_block(r), decl(r, 101).param) == (480, [240, 240])


def test_block_with_duration_zero_has_no_subblocks_and_is_read():
    r = report(B.build(stereo_with([B.ParameterBlockSpec(100, 0, mode1=(0, 480))])))
    b = the_block(r)
    assert (b.duration, b.subblocks, b.payload_read, b.extra_bytes) == (0, [], True, 0)
    assert m.parameter_block_timing(b, decl(r, 100).param) == (0, [])


def test_bytes_after_the_syntax_are_counted_not_read():
    r = report(B.build(one_block(B.mix_gain_data(STEP, Q(-6.0)), trailing=b"\xde\xad\xbe")))
    b = the_block(r)
    assert (b.payload_read, b.extra_bytes, len(b.subblocks)) == (True, 3, 1)
    no_findings_moved(r)


def test_blocks_are_kept_in_file_order_with_their_offsets():
    spec = stereo_with([
        B.ParameterBlockSpec(100, 0, mode1=(480, 480),
                             subblocks=[B.SubblockSpec(B.mix_gain_data(STEP, 1))]),
        B.ParameterBlockSpec(101, 0, subblocks=[B.SubblockSpec(B.mix_gain_data(STEP, 2))]),
        B.ParameterBlockSpec(100, 1, mode1=(480, 480),
                             subblocks=[B.SubblockSpec(B.mix_gain_data(STEP, 3))])],
        output_gain=B.ParamDefSpec(0, parameter_id=101, mode=0, duration=480,
                                   constant_subblock_duration=480))
    r = report(B.build(spec))
    blocks = r.model.parameter_blocks
    assert [b.parameter_id for b in blocks] == [100, 101, 100] == r.model.parameter_block_ids
    assert [b.subblocks[0].data.gain.start_point_value for b in blocks] == [1, 2, 3]
    assert blocks[0].header.file_offset < blocks[1].header.file_offset < blocks[2].header.file_offset
    assert r.model.obu_order.count("ParameterBlock") == 3


# ========================================================== blocks: mix gain
@pytest.mark.parametrize("anim,values,expected", [
    (STEP, (Q(-6.0),), (Q(-6.0), None, None, None)),
    (LINEAR, (Q(-6.0), Q(0.0)), (Q(-6.0), 0, None, None)),
    (BEZIER, (Q(-6.0), Q(0.0), Q(-2.0), 128), (Q(-6.0), 0, Q(-2.0), 128)),
    (INTER_LINEAR, (Q(3.0),), (None, Q(3.0), None, None)),
    (INTER_BEZIER, (Q(3.0), Q(1.0), 255), (None, Q(3.0), Q(1.0), 255)),
])
def test_every_mix_gain_animation_type_is_read(anim, values, expected):
    fields = ("start", "end", "control", "time")
    if anim in (INTER_LINEAR, INTER_BEZIER):
        fields = ("end", "control", "time")
    data = B.mix_gain_data(anim, **dict(zip(fields, values)))
    r = report(B.build(one_block(data)))
    b = the_block(r)
    assert b.payload_read, b.read_error
    g = b.subblocks[0].data
    assert isinstance(g, m.MixGainParameterData) and g.animation_type == anim
    assert (g.gain.start_point_value, g.gain.end_point_value, g.gain.control_point_value,
            g.gain.control_point_relative_time) == expected
    assert b.extra_bytes == 0
    no_findings_moved(r)


def test_mix_gain_values_are_signed_q7_8_as_coded():
    r = report(B.build(one_block(B.mix_gain_data(LINEAR, -32768, 32767))))
    g = the_block(r).subblocks[0].data.gain
    assert (g.start_point_value, g.end_point_value) == (-32768, 32767)


def test_undefined_animation_type_stops_the_read_and_is_a_note():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 240), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, Q(-1.0))),
        B.SubblockSpec(B.mix_gain_data(5, Q(-2.0)))])])
    r = report(B.build(spec))
    b = the_block(r)
    assert not b.payload_read and "animation_type 5 is not one IAMF v2.0.0 defines" in b.read_error
    assert len(b.subblocks) == 1                   # the subblock before it is kept
    (note,) = block_notes(r)
    assert note.startswith("parameter block for parameter_id 100 at byte ")
    assert note.endswith("; its payload is not read") and "animation_type 5" in note
    no_findings_moved(r)


# ========================================================== blocks: demixing
@pytest.mark.parametrize("mode,reserved", [(0, 0), (3, 0), (6, 0x1F), (7, 5)])
def test_demixing_block_is_read(mode, reserved):
    spec = B.channel_spec("5.1")
    spec.elements[0].params = [B.ParamDefSpec(1, parameter_id=200, mode=0, duration=480,
                                              constant_subblock_duration=480)]
    spec.parameter_blocks = [B.ParameterBlockSpec(200, 0, subblocks=[
        B.SubblockSpec(B.demixing_data(mode, reserved))])]
    r = report(B.build(spec))
    b = the_block(r)
    assert b.payload_read and b.param_definition_type == 1
    d = b.subblocks[0].data
    assert isinstance(d, m.DemixingInfoParameterData)
    assert (d.dmixp_mode, d.reserved) == (mode, reserved)
    no_findings_moved(r)


# ======================================================== blocks: recon gain
def scalable(layers: list[tuple[int, bool]]) -> B.IAMFSpec:
    """A channel element with the given (loudspeaker_layout,
    recon_gain_is_present) layers, each of one substream, declaring recon
    gain id 201 and demixing id 200 in mode 0."""
    spec = B.channel_spec("stereo")
    e = spec.elements[0]
    e.substream_ids = list(range(len(layers)))
    e.params = [B.ParamDefSpec(1, parameter_id=200, mode=0, duration=480,
                               constant_subblock_duration=480),
                B.ParamDefSpec(2, parameter_id=201, mode=0, duration=480,
                               constant_subblock_duration=480)]
    w = B.Writer().u8((len(layers) & 0x7) << 5)
    for lsl, rg in layers:
        w.u8(((lsl & 0xF) << 4) | (int(rg) << 2)).u8(1).u8(0)
    e.raw_config = w.bytes()
    return spec


def test_recon_gain_block_is_read_by_layer():
    spec = scalable([(1, False), (2, True), (7, True)])
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, subblocks=[B.SubblockSpec(
        B.recon_gain_data([(0b0000100, {2: 255}), (0b0011000, {3: 200, 4: 100})]))])]
    r = report(B.build(spec))
    b = the_block(r)
    assert b.payload_read, b.read_error
    d = b.subblocks[0].data
    assert isinstance(d, m.ReconGainInfoParameterData)
    assert d.layers[0] is None
    assert (d.layers[1].recon_gain_flags, d.layers[1].recon_gains) == (0b100, {2: 255})
    assert (d.layers[2].recon_gain_flags, d.layers[2].recon_gains) == (0x18, {3: 200, 4: 100})
    no_findings_moved(r)


def test_recon_gain_flags_above_bit_6_take_the_second_leb128_byte():
    spec = scalable([(2, True)])
    flags = (1 << 11) | (1 << 7) | 1                       # LFE, Lrs, L
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, subblocks=[B.SubblockSpec(
        B.recon_gain_data([(flags, {0: 10, 7: 20, 11: 30})]))])]
    r = report(B.build(spec))
    layer = the_block(r).subblocks[0].data.layers[0]
    assert layer.recon_gain_flags == flags
    assert layer.recon_gains == {0: 10, 7: 20, 11: 30}


def test_recon_gain_bits_past_12_are_kept_in_the_flags_and_read_no_gain():
    spec = scalable([(2, True)])
    flags = (1 << 13) | (1 << 12) | (1 << 2)               # two bits no channel owns
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, subblocks=[B.SubblockSpec(
        B.recon_gain_data([(flags, {2: 99})]))])]
    r = report(B.build(spec))
    b = the_block(r)
    layer = b.subblocks[0].data.layers[0]
    assert (layer.recon_gain_flags, layer.recon_gains, b.extra_bytes) == (flags, {2: 99}, 0)


def test_recon_gain_with_no_flagged_layer_reads_zero_bytes():
    spec = scalable([(1, False), (2, False)])
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, subblocks=[B.SubblockSpec(b"")])]
    r = report(B.build(spec))
    b = the_block(r)
    assert b.payload_read and b.subblocks[0].data.layers == [None, None]


def test_recon_gain_for_an_element_without_layers_reads_nothing():
    # declared on a scene-based element: no ChannelAudioLayerConfig to go by
    spec = B.scene_spec(1)
    spec.elements[0].params = [B.ParamDefSpec(2, parameter_id=201, mode=0, duration=480,
                                              constant_subblock_duration=480)]
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, subblocks=[B.SubblockSpec(b"\x07")])]
    r = report(B.build(spec))
    b = the_block(r)
    assert b.payload_read and b.subblocks[0].data.layers == [] and b.extra_bytes == 1


# ========================================================== blocks: position
POSITION_VALUES = {
    # per type: one STEP triple per object, with the sign and range edges
    POLAR: [(-180, -90, 127)], CART8: [(-128, 127, 0)], CART16: [(-32768, 32767, 1)],
    DUAL_POLAR: [(180, 90, 0), (-1, -1, 1)],
    DUAL_CART8: [(-1, 1, 0), (127, -128, 64)],
    DUAL_CART16: [(-1, 1, 0), (32767, -32768, 16384)],
}


def object_with_blocks(ptype: int, blocks: list[B.ParameterBlockSpec]) -> B.IAMFSpec:
    spec = B.object_spec(dual=ptype >= DUAL_POLAR, ptype=ptype)
    spec.parameter_blocks = blocks
    return spec


@pytest.mark.parametrize("ptype", list(POSITION_VALUES))
def test_position_step_block_of_every_type_is_read(ptype):
    objects = POSITION_VALUES[ptype]
    spec = object_with_blocks(ptype, [B.ParameterBlockSpec(2000, 0, mode1=(8, 8), subblocks=[
        B.SubblockSpec(B.position_data(ptype, STEP, objects))])])
    r = report(B.build(spec))
    b = the_block(r)
    assert b.payload_read, b.read_error
    d = b.subblocks[0].data
    assert isinstance(d, m.PositionParameterData) and d.animation_type == STEP
    assert [tuple(v.start_point_value for v in obj) for obj in d.objects] == objects
    assert all(v.end_point_value is None for obj in d.objects for v in obj)
    assert b.extra_bytes == 0 and b.param_definition_type == ptype
    no_findings_moved(r)


@pytest.mark.parametrize("ptype", list(POSITION_VALUES))
def test_position_inter_linear_block_of_every_type_is_read(ptype):
    objects = POSITION_VALUES[ptype]
    spec = object_with_blocks(ptype, [B.ParameterBlockSpec(2000, 0, mode1=(8, 8), subblocks=[
        B.SubblockSpec(B.position_data(ptype, INTER_LINEAR, objects))])])
    d = the_block(report(B.build(spec))).subblocks[0].data
    assert d.animation_type == INTER_LINEAR
    assert [tuple(v.end_point_value for v in obj) for obj in d.objects] == objects
    assert all(v.start_point_value is None for obj in d.objects for v in obj)


@pytest.mark.parametrize("ptype", [POLAR, CART8, DUAL_CART16])
def test_position_inter_bezier_block_packs_control_point_and_time(ptype):
    n = 2 if ptype >= DUAL_POLAR else 1
    objects = [((10, 20, 128), (-30, 40, 255), (100, 50, 0))[:3]] * n
    spec = object_with_blocks(ptype, [B.ParameterBlockSpec(2000, 0, mode1=(8, 8), subblocks=[
        B.SubblockSpec(B.position_data(ptype, INTER_BEZIER, objects))])])
    b = the_block(report(B.build(spec)))
    assert b.payload_read, b.read_error
    d = b.subblocks[0].data
    assert d.animation_type == INTER_BEZIER
    for obj in d.objects:
        assert [(v.end_point_value, v.control_point_value, v.control_point_relative_time)
                for v in obj] == [(10, 20, 128), (-30, 40, 255), (100, 50, 0)]
        assert all(v.start_point_value is None for v in obj)
    assert b.extra_bytes == 0


@pytest.mark.parametrize("ptype", [POLAR, DUAL_POLAR, CART16])
def test_position_linear_and_bezier_syntax_is_read_even_where_not_allowed(ptype):
    # The syntax exists for every animation type; whether a polar block may
    # use LINEAR or BEZIER is a later judgement, not the reader's.
    n = 2 if ptype >= DUAL_POLAR else 1
    lin = [((1, 2), (3, 4), (5, 6))] * n
    bez = [((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12))] * n
    spec = object_with_blocks(ptype, [
        B.ParameterBlockSpec(2000, 0, mode1=(8, 8),
                             subblocks=[B.SubblockSpec(B.position_data(ptype, LINEAR, lin))]),
        B.ParameterBlockSpec(2000, 1, mode1=(8, 8),
                             subblocks=[B.SubblockSpec(B.position_data(ptype, BEZIER, bez))])])
    r = report(B.build(spec))
    a, b = r.model.parameter_blocks
    assert a.payload_read and b.payload_read
    for obj in a.subblocks[0].data.objects:
        assert [(v.start_point_value, v.end_point_value) for v in obj] == [(1, 2), (3, 4), (5, 6)]
    for obj in b.subblocks[0].data.objects:
        assert [(v.start_point_value, v.end_point_value, v.control_point_value,
                 v.control_point_relative_time) for v in obj] == [
                    (1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12)]


def test_polar_block_bits_are_packed_9_8_7_msb_first():
    # azimuth -90 (9 bits 110100110), elevation 0, distance 127: d3 00 7f,
    # the layout the definition's default uses too
    spec = object_with_blocks(POLAR, [B.ParameterBlockSpec(2000, 0, mode1=(8, 8), subblocks=[
        B.SubblockSpec(b"\x03\xd3\x00\x7f")])])
    d = the_block(report(B.build(spec))).subblocks[0].data
    assert d.animation_type == INTER_LINEAR
    assert tuple(v.end_point_value for v in d.objects[0]) == (-90, 0, 127)
    assert B.position_data(POLAR, INTER_LINEAR, [(-90, 0, 127)]) == b"\x03\xd3\x00\x7f"


def test_position_blocks_with_several_subblocks_stay_byte_aligned():
    spec = object_with_blocks(CART8, [B.ParameterBlockSpec(2000, 0, mode1=(8, 4), subblocks=[
        B.SubblockSpec(B.position_data(CART8, INTER_LINEAR, [(1, 2, 3)])),
        B.SubblockSpec(B.position_data(CART8, INTER_LINEAR, [(4, 5, 6)]))])])
    b = the_block(report(B.build(spec)))
    assert [tuple(v.end_point_value for v in sb.data.objects[0]) for sb in b.subblocks] == [
        (1, 2, 3), (4, 5, 6)]
    assert b.extra_bytes == 0


# ================================================ blocks: momentary loudness
def test_momentary_loudness_block_is_read_by_its_loudness_info_definition():
    spec = B.channel_spec("stereo")
    spec.mixes[0].layouts[0].momentary = B.MomentarySpec(
        B.ParamDefSpec(9, parameter_id=127, mode=0, duration=480, constant_subblock_duration=480))
    spec.parameter_blocks = [B.ParameterBlockSpec(127, tu, subblocks=[B.SubblockSpec(
        B.momentary_loudness_data(18 + tu, reserved=tu))]) for tu in range(2)]
    r = report(B.build(spec))
    a, b = r.model.parameter_blocks
    assert a.payload_read and b.payload_read and a.param_definition_type == 9
    assert (a.subblocks[0].data.momentary_loudness, a.subblocks[0].data.reserved) == (18, 0)
    assert (b.subblocks[0].data.momentary_loudness, b.subblocks[0].data.reserved) == (19, 1)
    no_findings_moved(r)


# ======================================================= blocks: not readable
def test_block_of_an_undeclared_id_is_a_note_and_not_read():
    r = report(B.build(stereo_with([B.ParameterBlockSpec(777, 0, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 0))])])))
    b = the_block(r)
    assert (b.parameter_id, b.param_definition_type, b.param_definition_mode,
            b.payload_read, b.subblocks) == (777, None, None, False, [])
    assert b.read_error == "no Audio Element or Mix Presentation declares parameter_id 777"
    assert block_notes(r) == [f"parameter block for parameter_id 777 at byte "
                              f"{b.header.file_offset}: {b.read_error}; its payload is not read"]
    assert r.model.parameter_block_ids == [777]
    no_findings_moved(r)
    assert r.exit_code() == 0


def test_block_before_its_declaration_is_not_read():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 0))])])
    raw = B.build(spec)
    mp = B._mix_presentation(spec.mixes[0])
    pb = spec.parameter_blocks[0].bytes()
    moved = raw.replace(mp + pb, pb + mp)              # the block precedes its Mix Presentation
    assert moved != raw
    r = validate_bytes(moved)
    assert not the_block(r).payload_read and "declares parameter_id 100" in the_block(r).read_error
    assert r.model.parse_errors == []


def test_subblock_count_the_payload_cannot_hold_is_a_note():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 0), num_subblocks=1000,
                                             subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 1), duration=240),
        B.SubblockSpec(B.mix_gain_data(STEP, 2), duration=240)])])
    r = report(B.build(spec))
    b = the_block(r)
    assert (b.num_subblocks, b.payload_read, len(b.subblocks)) == (1000, False, 2)
    assert "truncated" in b.read_error
    assert len(block_notes(r)) == 1
    no_findings_moved(r)


def test_subblock_count_past_the_ceiling_is_a_note_and_no_hang():
    # zero-byte subblocks (recon gain with no flagged layer) bound nothing on
    # their own: the reader's ceiling does
    spec = scalable([(1, False), (2, False)])
    spec.elements[0].params[1] = B.ParamDefSpec(2, parameter_id=201)      # mode 1
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, mode1=(1 << 40, 1))]
    r = report(B.build(spec))
    b = the_block(r)
    assert not b.payload_read and b.subblocks == []
    assert b.read_error.startswith(f"num_subblocks {1 << 40} is more than this reader "
                                   f"follows ({m.MAX_PARAMETER_SUBBLOCKS}) (at byte ")
    no_findings_moved(r)


def test_subblock_count_at_the_ceiling_is_followed():
    spec = scalable([(1, False), (2, False)])
    spec.elements[0].params[1] = B.ParamDefSpec(2, parameter_id=201)
    spec.parameter_blocks = [B.ParameterBlockSpec(201, 0, mode1=(m.MAX_PARAMETER_SUBBLOCKS, 1))]
    b = the_block(report(B.build(spec)))
    assert b.payload_read and len(b.subblocks) == m.MAX_PARAMETER_SUBBLOCKS


TRUNCATION_SHAPES = {
    "mix gain BEZIER, mode 1, two subblocks": stereo_with([B.ParameterBlockSpec(
        100, 0, mode1=(480, 0), subblocks=[
            B.SubblockSpec(B.mix_gain_data(BEZIER, 1, 2, 3, 4), duration=240),
            B.SubblockSpec(B.mix_gain_data(INTER_BEZIER, end=5, control=6, time=7),
                           duration=240)])]),
    "dual polar INTER_BEZIER": object_with_blocks(DUAL_POLAR, [B.ParameterBlockSpec(
        2000, 0, mode1=(8, 8), subblocks=[B.SubblockSpec(B.position_data(
            DUAL_POLAR, INTER_BEZIER, [((1, 2, 3), (4, 5, 6), (7, 8, 9))] * 2))])]),
    "recon gain two layers": (lambda s: (setattr(s, "parameter_blocks", [B.ParameterBlockSpec(
        201, 0, subblocks=[B.SubblockSpec(B.recon_gain_data(
            [((1 << 11) | 1, {0: 1, 11: 2}), (0x7f, dict.fromkeys(range(7), 3))]))])]), s)[1])(
        scalable([(2, True), (7, True)])),
}


@pytest.mark.parametrize("shape", list(TRUNCATION_SHAPES))
def test_truncation_at_every_payload_byte_is_structured(shape):
    spec = TRUNCATION_SHAPES[shape]
    (pb,) = spec.parameter_blocks
    full = pb.bytes()
    whole = report(B.build(spec))
    assert the_block(whole).payload_read, the_block(whole).read_error
    payload_len = len(full) - len(B.obu(3, b""))
    pid_len = len(B.Writer().leb128(pb.parameter_id).bytes())
    for n in range(pid_len, payload_len):           # every cut after parameter_id
        pb.truncate = n
        r = report(B.build(spec))
        b = the_block(r)
        assert not b.payload_read and "truncated" in b.read_error, (n, b.read_error)
        assert len(block_notes(r)) == 1 and r.model.parse_errors == [], n
        assert len(r.model.audio_frames) == len(whole.model.audio_frames), n
    pb.truncate = 0                                 # even parameter_id is gone: S-108 as before
    r = report(B.build(spec))
    assert r.model.parameter_blocks == [] and len(r.model.parse_errors) == 1
    assert any(f.check_id == "S-108" for f in r.findings)
    pb.truncate = None


def test_a_block_cut_short_leaves_the_frames_after_it_readable():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 1))], truncate=3)])
    r = report(B.build(spec))
    assert not the_block(r).payload_read
    assert len(r.model.audio_frames) == 2 and r.exit_code() == 0     # 2 TUs x 1 substream


# ======================================================================= MP4
def test_mp4_samples_carry_the_blocks_into_the_model():
    spec = B.animated_spec()
    raw = B.build(spec)
    want = report(raw).model
    got = report(wrap_mp4(wrap := raw)).model
    assert got.container == "mp4" and len(got.parameter_blocks) == 6
    assert [b.parameter_id for b in got.parameter_blocks] == [b.parameter_id
                                                               for b in want.parameter_blocks]
    assert got.parameter_block_ids == want.parameter_block_ids
    for a, b in zip(got.parameter_blocks, want.parameter_blocks):
        assert (a.payload_read, a.subblocks, a.duration) == (b.payload_read, b.subblocks,
                                                             b.duration)
    assert got.parameter_definitions.keys() == want.parameter_definitions.keys()
    assert render_json(report(wrap)).count('"parameters"') == 1


def test_mp4_block_notes_come_along_with_the_samples():
    spec = stereo_with([B.ParameterBlockSpec(777, 1, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 0))])])
    r = report(wrap_mp4(B.build(spec)))
    (b,) = r.model.parameter_blocks
    assert not b.payload_read
    (note,) = [n for n in r.model.parse_notes if "parameter block" in n]
    assert note.startswith("MP4 samples (offsets in the reconstructed IA stream): "
                           "parameter block for parameter_id 777")
    assert r.model.parse_errors == []


def test_mp4_wrap_puts_a_leading_block_in_its_temporal_units_sample():
    from fixtures.mp4wrap import split_stream
    spec = stereo_with([B.ParameterBlockSpec(100, tu, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, tu))]) for tu in range(2)])
    desc, tus = split_stream(B.build(spec))
    assert len(tus) == 2
    assert all(tu[0] >> 3 == 3 for tu in tus)                  # each sample opens on its block
    assert desc.count(bytes([3 << 3])) == 0 or parse_bytes(desc).parameter_blocks == []


def test_fragmented_mp4_reaches_no_block():
    # no sample tables: the engine has nothing to re-walk, so the model has
    # no blocks and the report no parameters key (a known gap, not a fact
    # about the stream)
    spec = B.animated_spec()
    data = wrap_mp4(B.build(spec))
    stripped = data.replace(b"stsz", b"xxxx")
    r = validate_bytes(stripped)
    assert r.model is not None and r.model.parameter_blocks == []
    assert '"parameters"' not in render_json(r)


# ================================================================ the report
def test_json_parameters_entry_per_declared_id_when_blocks_exist():
    spec = B.animated_spec()
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    params = {p["parameter_id"]: p for p in stream["parameters"]}
    assert set(params) == {100, 101, 200}
    assert params[100] == {
        "parameter_id": 100, "type": "MIX_GAIN", "parameter_rate": 48000,
        "param_definition_mode": 1, "default_mix_gain_db": -3.0,
        "declared": [{"role": "element_mix_gain", "mix_presentation_id": 42, "sub_mix": 1,
                      "audio_element_id": 300}],
        "blocks": 2, "duration_ticks": 960, "block_duration": {"min": 480, "max": 480},
        "subblocks": 2, "animation_types": ["STEP"], "gain_db": {"min": -4.0, "max": -3.0}}
    assert params[101]["declared"] == [{"role": "output_mix_gain", "mix_presentation_id": 42,
                                        "sub_mix": 1}]
    assert (params[101]["param_definition_mode"], params[101]["duration"],
            params[101]["constant_subblock_duration"]) == (0, 480, 480)
    assert params[101]["animation_types"] == ["LINEAR"]
    assert params[101]["gain_db"] == {"min": -2.0, "max": 0.0}
    assert params[200]["declared"] == [{"role": "demixing", "audio_element_id": 300}]
    assert (params[200]["type"], params[200]["dmixp_modes"]) == ("DEMIXING", [1, 2])
    assert "gain_db" not in params[200] and "default_mix_gain_db" not in params[200]


def test_json_parameters_lists_ids_without_blocks_and_blocks_without_ids():
    spec = stereo_with([B.ParameterBlockSpec(777, 0, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 0))])])
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    params = {p["parameter_id"]: p for p in stream["parameters"]}
    assert params[100]["blocks"] == 0 and "duration_ticks" not in params[100]
    assert params[777] == {"parameter_id": 777, "declared": [], "blocks": 1, "blocks_not_read": 1}


def test_json_parameters_show_recon_gain_position_and_loudness_ranges():
    spec = scalable([(2, True), (7, True)])
    spec.parameter_blocks = [B.ParameterBlockSpec(201, tu, subblocks=[B.SubblockSpec(
        B.recon_gain_data([(1, {0: 40 + tu}), (0x18, {3: 255, 4: 7})]))]) for tu in range(2)]
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    params = {p["parameter_id"]: p for p in stream["parameters"]}
    assert params[201]["recon_gain"] == {"min": 7, "max": 255} and params[201]["blocks"] == 2
    assert params[200]["blocks"] == 0

    spec = object_with_blocks(DUAL_POLAR, [B.ParameterBlockSpec(2000, 0, mode1=(8, 8), subblocks=[
        B.SubblockSpec(B.position_data(DUAL_POLAR, INTER_LINEAR, [(-90, 10, 127), (90, -10, 0)]))])])
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    (p,) = [p for p in stream["parameters"] if p["parameter_id"] == 2000]
    assert p["type"] == "DUAL_POLAR" and p["animation_types"] == ["INTER_LINEAR"]
    assert p["position"] == {"azimuth": {"min": -90, "max": 90},
                             "elevation": {"min": -10, "max": 10},
                             "distance": {"min": 0, "max": 127}}
    assert p["declared"] == [{"role": "position", "mix_presentation_id": 42, "sub_mix": 1,
                              "audio_element_id": 300}]

    spec = B.channel_spec("stereo")
    spec.mixes[0].layouts[0].momentary = B.MomentarySpec(
        B.ParamDefSpec(9, parameter_id=127, mode=0, duration=480, constant_subblock_duration=480))
    spec.parameter_blocks = [B.ParameterBlockSpec(127, 0, subblocks=[B.SubblockSpec(
        B.momentary_loudness_data(23))])]
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    (p,) = [p for p in stream["parameters"] if p["parameter_id"] == 127]
    assert p["momentary_loudness_lkfs"] == {"min": -23, "max": -23}
    assert p["declared"] == [{"role": "momentary_loudness", "mix_presentation_id": 42,
                              "sub_mix": 1, "layout": 1}]


def test_json_marks_differing_declarations_of_one_id():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(STEP, 0))])],
        output_gain=B.ParamDefSpec(0, parameter_id=100, rate=24000))
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    (p,) = stream["parameters"]
    assert p["declarations_differ"] is True and len(p["declared"]) == 2
    spec.mixes[0].output_mix_gain = B.ParamDefSpec(0, parameter_id=100)
    stream = json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
    assert stream["parameters"][0]["declarations_differ"] is False


def test_json_blocks_not_read_are_counted():
    spec = stereo_with([B.ParameterBlockSpec(100, 0, mode1=(480, 480), subblocks=[
        B.SubblockSpec(B.mix_gain_data(5, 0))])])
    (p,) = [p for p in json.loads(render_json(report(B.build(spec))))["summary"]["stream"]
            ["parameters"] if p["parameter_id"] == 100]
    assert (p["blocks"], p["blocks_not_read"]) == (1, 1) and "duration_ticks" not in p


@pytest.mark.parametrize("name", ["stereo", "5.1", "foa", "object", "dual-object"])
def test_report_of_a_stream_without_blocks_has_no_parameters_key(name):
    spec = B.all_valid_specs()[name]
    for data in (B.build(spec), wrap_mp4(B.build(spec))):
        r = report(data)
        assert r.model.parameter_definitions                  # every stream declares gains
        doc = json.loads(render_json(r))
        assert "parameters" not in doc["summary"]["stream"]
        assert "  parameter:" not in render_text(r)
        assert "parameter: parameter_id" not in render_html(r)


def test_text_and_html_carry_a_parameter_line_per_id():
    r = report(B.build(B.animated_spec()))
    text = render_text(r)
    lines = [ln for ln in text.splitlines() if ln.startswith("  parameter:")]
    assert lines == [
        "  parameter: parameter_id 200 DEMIXING (demixing of audio_element 300): 2 blocks, "
        "960 ticks at 48000/s, dmixp_mode 1, 2",
        "  parameter: parameter_id 100 MIX_GAIN (element_mix_gain in mix_presentation 42): "
        "2 blocks, 960 ticks at 48000/s, STEP, gain -4.00..-3.00 dB",
        "  parameter: parameter_id 101 MIX_GAIN (output_mix_gain in mix_presentation 42): "
        "2 blocks, 960 ticks at 48000/s, LINEAR, gain -2.00..+0.00 dB"]
    html = render_html(r)
    assert "parameter: parameter_id 100 MIX_GAIN" in html and "gain -4.00..-3.00 dB" in html


def test_text_line_for_unread_undeclared_and_position_blocks():
    spec = object_with_blocks(POLAR, [
        B.ParameterBlockSpec(2000, 0, mode1=(8, 8), subblocks=[
            B.SubblockSpec(B.position_data(POLAR, STEP, [(-90, 0, 127)]))]),
        B.ParameterBlockSpec(5, 1, mode1=(8, 8), subblocks=[B.SubblockSpec(b"\x00")])])
    text = render_text(report(B.build(spec)))
    assert ("  parameter: parameter_id 2000 POLAR (position in mix_presentation 42): 1 block, "
            "8 ticks at 48000/s, STEP, azimuth -90..-90 elevation 0..0 distance 127..127/127"
            in text)
    assert "  parameter: parameter_id 5 (not declared by any descriptor): 1 block (1 not read)" in text


# ============================================================ model helpers
def test_parameter_block_timing_helper_splits_as_the_specification_says():
    assert m.implied_num_subblocks(960, 960) == 1
    assert m.implied_num_subblocks(1000, 300) == 4
    b = m.ParameterBlock(1, m.OBUHeader(3, False, False, False, 0), param_definition_mode=1,
                         duration=1000, constant_subblock_duration=300)
    assert m.parameter_block_timing(b, None) == (1000, [300, 300, 300, 100])
    b.constant_subblock_duration = 0
    b.subblocks = [m.ParameterSubblock(600), m.ParameterSubblock(400)]
    assert m.parameter_block_timing(b, None) == (1000, [600, 400])
    pd = m.ParamDefinition(0, 1, 48000, 0, duration=480, constant_subblock_duration=0,
                           num_subblocks=2, subblock_durations=[200, 280])
    b0 = m.ParameterBlock(1, b.header, param_definition_mode=0)
    assert m.parameter_block_timing(b0, pd) == (480, [200, 280])
    assert m.parameter_block_timing(m.ParameterBlock(1, b.header), pd) == (None, [])


def test_bit_reader_reads_msb_first_signed_and_unsigned():
    from sentinel.reader import BitReader, ByteReader, ParseError
    bits = BitReader(ByteReader(b"\xd3\x00\x7f\x80"))
    assert (bits.s(9), bits.s(8), bits.u(7)) == (-90, 0, 127)
    assert bits.bits_pending == 0
    assert bits.s(1) == -1 and bits.bits_pending == 7
    assert bits.u(7) == 0 and bits.bits_pending == 0
    with pytest.raises(ParseError):
        bits.u(1)
