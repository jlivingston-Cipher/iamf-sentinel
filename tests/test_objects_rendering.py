"""Object-based elements and the rendering settings IAMF v2.0.0 adds
(S-210..S-217), and the parser that reads them.

Two halves. The first is the reading: ObjectsConfig(), and what v2.0.0 placed
inside RenderingConfig()'s extension envelope — num_parameters, the six
position parameter definitions, ElementGainOffsetConfig() — plus the
binaural_filter_profile bits of its first byte. The second is the checks.

Every rule is exercised as a pair synthesised by fixtures/: an input that
sits on the allowed side and says nothing, and one a step past it that fires.
Test names say which is which — ``_silent`` expects no S-21x finding at all,
``_fires`` expects the one named — because a test that has only ever passed
proves nothing: with the rule removed from the checks, every ``_fires`` test
has to fail.

Expected severities and limits are written out here, not read from the module
under test. Citations (``v2:`` IAMF v2.0.0, by source line of index.bs at
4d2c6da) are beside each rule in sentinel/checks/l2_semantics.py.

Positions over time are not covered: the Parameter Block OBUs that a position
definition points at are not read by this package.

All bytes are synthesised by fixtures/ — no reference vectors are involved.
"""

from __future__ import annotations

import json

import pytest

from fixtures import build as B
from fixtures.mp4wrap import wrap_mp4
from sentinel import model as m
from sentinel.engine import validate_bytes
from sentinel.findings import REGISTRY, Severity

OBJECT_CHECKS = ("S-210", "S-211", "S-212", "S-213", "S-214", "S-215", "S-216",
                 "S-217")
DEFAULT_SEVERITY = {"S-210": Severity.FAIL, "S-211": Severity.FAIL,
                    "S-212": Severity.FAIL, "S-213": Severity.WARN,
                    "S-214": Severity.WARN, "S-215": Severity.WARN,
                    "S-216": Severity.WARN, "S-217": Severity.FAIL}
POLAR, CART8, CART16, DUAL_POLAR, DUAL_CART8, DUAL_CART16 = 3, 4, 5, 6, 7, 8
SINGLE, DUAL = (POLAR, CART8, CART16), (DUAL_POLAR, DUAL_CART8, DUAL_CART16)
TYPE_NAME = {3: "POLAR", 4: "CART8", 5: "CART16", 6: "DUAL_POLAR",
             7: "DUAL_CART8", 8: "DUAL_CART16"}
LAYOUTS = [B.LayoutSpec(0, -18.0, -6.0, -5.0)]
# A valid default position for each definition type, one triple per object.
VALID_DEFAULTS = {
    POLAR: [(30, 10, 127)], CART8: [(-64, 127, 0)], CART16: [(-16384, 32767, 0)],
    DUAL_POLAR: [(30, 10, 127), (-30, 10, 127)],
    DUAL_CART8: [(-64, 127, 0), (64, 127, 0)],
    DUAL_CART16: [(-16384, 32767, 0), (16384, 32767, 0)],
}


def position(ptype: int, defaults=None, **kw) -> B.PositionSpec:
    return B.PositionSpec(ptype, VALID_DEFAULTS[ptype] if defaults is None else defaults,
                          **kw)


def rendering(spec: B.IAMFSpec, ae_id: int = 300, mix: int = 0) -> B.RenderingSpec:
    """The RenderingSpec of one element of a fixture's mix, created on demand."""
    return spec.mixes[mix].rendering.setdefault(ae_id, B.RenderingSpec())


def report(spec: B.IAMFSpec):
    r = validate_bytes(B.build(spec))
    assert r.execution_error is None, r.execution_error
    return r


def s21x(r) -> list[tuple[str, Severity]]:
    """Every object / rendering finding of a report, as (check id, severity)."""
    return [(f.check_id, f.severity) for f in r.findings if f.check_id in OBJECT_CHECKS]


def messages(r, check_id: str) -> list[str]:
    return [f.message for f in r.findings if f.check_id == check_id]


def assert_silent(r) -> None:
    assert s21x(r) == [], [f.to_dict() for f in r.findings if f.check_id in OBJECT_CHECKS]


def assert_only(r, check_id: str, severity: Severity, *needles: str) -> str:
    """Exactly one object / rendering finding in the report: that check, that
    severity, those words. Returns its message."""
    assert s21x(r) == [(check_id, severity)], [
        f.to_dict() for f in r.findings if f.check_id in OBJECT_CHECKS]
    (msg,) = messages(r, check_id)
    for needle in needles:
        assert needle in msg, (needle, msg)
    return msg


def rc_of(r, mix: int = 0, sub_mix: int = 0, element: int = 0) -> m.RenderingConfig:
    return r.model.mix_presentations[mix].sub_mixes[sub_mix].rendering_configs[element]


def s108(r) -> list[str]:
    return [f.message for f in r.findings if f.check_id == "S-108"]


# ============================================================== the registry
def test_registry_rows_and_default_severities():
    for check_id, severity in DEFAULT_SEVERITY.items():
        row = REGISTRY[check_id]
        assert row.layer == "L2" and row.default_severity == severity
        assert row.title and row.description and row.f_refs == ()


# ===================================================== reading: ObjectsConfig
@pytest.mark.parametrize("num_objects", [1, 2])
def test_objects_config_is_in_the_model(num_objects):
    spec = B.object_spec(dual=num_objects == 2)
    spec.elements[0].objects_extension = b"\xaa\xbb"
    r = report(spec)
    ae = r.model.audio_elements[300]
    assert ae.audio_element_type == m.AUDIO_ELEMENT_OBJECT
    assert (ae.objects.objects_config_size, ae.objects.num_objects,
            ae.objects.extension_bytes) == (3, num_objects, 2)
    assert (ae.num_parameters, ae.num_substreams) == (0, 1)
    assert r.model.parse_notes == [] and r.model.parse_errors == []
    assert_silent(r)


# =================================================== reading: RenderingConfig
def test_v1_1_rendering_config_reads_as_before():
    # mode byte, extension size 0: nothing of v2.0.0 is read, and the fields
    # after the rendering_config are found where they always were
    r = report(B.channel_spec("stereo"))
    rc = rc_of(r)
    assert (rc.headphones_rendering_mode, rc.element_gain_offset_flag,
            rc.binaural_filter_profile, rc.reserved) == (0, False, 0, 0)
    assert rc.rendering_config_extension_size == 0 and rc.extension_read
    assert rc.num_parameters is None and rc.position_definitions == []
    assert rc.other_param_definition_types == [] and rc.element_gain_offset is None
    mp = r.model.mix_presentations[0]
    assert mp.annotations == ["Fixture Program"]
    assert [ll.label for ll in mp.sub_mixes[0].layouts] == ["Stereo"]
    assert r.model.parse_notes == []
    assert_silent(r)


def test_first_byte_is_split_into_its_four_fields():
    spec = B.channel_spec("stereo")
    rs = rendering(spec)
    rs.headphones_rendering_mode, rs.binaural_filter_profile, rs.reserved = 1, 2, 5
    assert rs.bytes() == bytes([0b01_0_10_101, 0x00])
    rc = rc_of(report(spec))
    assert (rc.headphones_rendering_mode, rc.element_gain_offset_flag,
            rc.binaural_filter_profile, rc.reserved) == (1, False, 2, 5)


def test_polar_defaults_are_packed_9_8_7_bits_msb_first():
    # azimuth 1, elevation 2, distance 3 then 4, 5, 6: 00 81 03 / 02 02 86,
    # the same six bytes AOM's conformance vectors carry for these values
    assert B.polar_bytes(1, 2, 3) + B.polar_bytes(4, 5, 6) == bytes.fromhex("008103020286")
    spec = B.object_spec(dual=True)
    rendering(spec).params = [position(DUAL_POLAR, [(1, 2, 3), (4, 5, 6)])]
    assert rc_of(report(spec)).position_definitions[0].defaults == [(1, 2, 3), (4, 5, 6)]


EXTREMES = {
    POLAR: [(-256, -128, 0)], CART8: [(-128, 127, -1)], CART16: [(-32768, 32767, -1)],
    DUAL_POLAR: [(255, 127, 127), (-180, -90, 64)],
    DUAL_CART8: [(127, -128, 0), (1, -1, 100)],
    DUAL_CART16: [(32767, -32768, 0), (256, -256, 1)],
}


@pytest.mark.parametrize("ptype", SINGLE + DUAL)
@pytest.mark.parametrize("defaults", ["valid", "extreme"])
def test_every_position_definition_type_is_read(ptype, defaults):
    values = VALID_DEFAULTS[ptype] if defaults == "valid" else EXTREMES[ptype]
    spec = B.object_spec(dual=ptype in DUAL)
    rendering(spec).params = [position(ptype, values, parameter_id=77, rate=24000)]
    r = report(spec)
    rc = rc_of(r)
    assert rc.extension_read and rc.num_parameters == 1 and rc.extension_bytes == 0
    (pd,) = rc.position_definitions
    assert pd.param_definition_type == ptype and pd.defaults == values
    assert (pd.param.parameter_id, pd.param.parameter_rate,
            pd.param.param_definition_mode) == (77, 24000, 1)
    assert r.model.parse_errors == [] and r.model.parse_notes == []


def test_position_definition_with_its_durations_is_read():
    # param_definition_mode 0: duration and constant_subblock_duration follow
    # the mode byte, before the default position
    ext = (B.Writer().leb128(1).leb128(POLAR).leb128(7).leb128(48000).u8(0x00)
           .leb128(1024).leb128(1024).raw(B.polar_bytes(-45, 20, 100)).bytes())
    spec = B.object_spec()
    rendering(spec).raw_extension = ext
    r = report(spec)
    (pd,) = rc_of(r).position_definitions
    assert (pd.param.param_definition_mode, pd.param.duration,
            pd.param.constant_subblock_duration) == (0, 1024, 1024)
    assert pd.defaults == [(-45, 20, 100)]
    assert_silent(r)


@pytest.mark.parametrize("gain,expected", [
    (("value", -768), (0, -768, None, None, None)),
    (("value", 32767), (0, 32767, None, None, None)),
    (("range", -768, -1536, 0), (1, None, -768, -1536, 0)),
    (("range", 256, -32768, 32767), (1, None, 256, -32768, 32767)),
])
def test_element_gain_offset_is_read(gain, expected):
    spec = B.channel_spec("stereo")
    rendering(spec).gain_offset = gain
    r = report(spec)
    rc = rc_of(r)
    g = rc.element_gain_offset
    assert rc.element_gain_offset_flag and rc.num_parameters == 0
    assert (g.element_gain_offset_type, g.element_gain_offset,
            g.default_element_gain_offset, g.min_element_gain_offset,
            g.max_element_gain_offset) == expected
    assert_silent(r)


def test_extension_bytes_after_the_known_fields_are_skipped():
    # position definition, gain offset, then reserved bytes: the envelope ends
    # where rendering_config_extension_size says, and the mix gain that
    # follows it is still found
    spec = B.object_spec()
    rs = rendering(spec)
    rs.gain_offset, rs.extension_bytes = ("value", -256), b"extra"
    r = report(spec)
    rc = rc_of(r)
    assert rc.extension_bytes == 5 and len(rc.position_definitions) == 1
    assert rc.element_gain_offset.element_gain_offset == -256
    assert rc.rendering_config_extension_size == len(rs.bytes()) - 2
    assert [ll.label for ll in r.model.mix_presentations[0].sub_mixes[0].layouts] == [
        "Stereo", "5.1"]
    assert r.model.parse_errors == [] and r.model.parse_notes == []
    assert_silent(r)


def test_num_parameters_zero_and_extension_bytes_alone_silent():
    # what a v2.0.0 encoder writes for a channel-based element that only
    # carries reserved extension bytes
    spec = B.channel_spec("stereo", profile=0)
    rendering(spec).extension_bytes = b"extra"
    r = report(spec)
    rc = rc_of(r)
    assert (rc.num_parameters, rc.extension_bytes) == (0, 5)
    assert r.model.parse_notes == []
    assert_silent(r)


@pytest.mark.parametrize("ptype", [0, 1, 2, 9, 10, 127, 128, 300])
def test_other_definition_types_are_skipped_by_their_size(ptype):
    # carried as param_definition_size + bytes whatever the type: the position
    # definition after it is still read
    spec = B.object_spec()
    rs = rendering(spec)
    rs.params = [(ptype, b"\x01\x02\x03"), position(POLAR)]
    rc = rc_of(report(spec))
    assert rc.other_param_definition_types == [ptype] and rc.num_parameters == 2
    assert [pd.defaults for pd in rc.position_definitions] == [VALID_DEFAULTS[POLAR]]


# ---------------------------------- extension bytes that are not v2.0.0 syntax
NOT_V2_SYNTAX = pytest.mark.parametrize("raw,flag,why", [
    (b"extra", None, "need 116 bytes"),               # 'e' parameters, type 'x', size 't'
    (b"\x01\x03\x01\x80\xf7\x02\x80\x00", None, "need 3 bytes"),   # POLAR, 1 of 3 bytes
    (b"\x00", True, "need 1 bytes"),                  # gain flag, no room for the type
    (b"", True, "leaves no room"),                    # gain flag, empty envelope
    (b"\x00\x01\xfd\x00\xfa", True, "need 2 bytes"),  # RANGE cut inside its third gain
    (b"\xff\xff\xff\xff\xff\xff\xff\x7f", None, "truncated"),      # 2^56 - 1 parameters
], ids=["v1-reserved-bytes", "cut-position", "cut-gain-type", "flag-empty-envelope",
        "cut-gain-range", "huge-num-parameters"])


def _not_v2(raw: bytes, flag, profile: int):
    spec = B.channel_spec("stereo", profile=profile)
    rs = rendering(spec)
    rs.raw_extension, rs.gain_offset_flag = raw, flag
    r = report(spec)
    rc = rc_of(r)
    # kept in the model with nothing of the envelope read, and the Mix
    # Presentation around it read in full: the envelope bounds the damage
    assert not rc.extension_read and rc.num_parameters is None
    assert rc.position_definitions == [] and rc.element_gain_offset is None
    assert rc.rendering_config_extension_size == len(raw)
    assert [ll.label for ll in r.model.mix_presentations[0].sub_mixes[0].layouts] == [
        "Stereo"]
    assert_silent(r)                     # no rendering check judges what was not read
    return r


@NOT_V2_SYNTAX
@pytest.mark.parametrize("profile", [0, 1, 2])
def test_unreadable_extension_under_older_profiles_is_a_note(raw, flag, why, profile):
    # Before v2.0.0 these bytes, and the flag bit, were reserved.
    r = _not_v2(raw, flag, profile)
    assert r.model.parse_errors == [] and s108(r) == []
    (note,) = r.model.parse_notes
    assert "does not follow the IAMF v2.0.0 syntax" in note and why in note


@NOT_V2_SYNTAX
@pytest.mark.parametrize("profile", [3, 4, 5])
def test_unreadable_extension_under_v2_profiles_is_a_parse_error_fires(
        raw, flag, why, profile):
    r = _not_v2(raw, flag, profile)
    (msg,) = s108(r)
    assert msg.startswith("structural parse problem: mix_presentation 42 / "
                          "audio_element 300: rendering_config extension does not "
                          "follow the IAMF v2.0.0 syntax (")
    assert why in msg
    assert r.exit_code() == 1


def test_unreadable_extension_under_a_v2_additional_profile_fires():
    spec = B.channel_spec("stereo", profile=1)
    spec.additional_profile = 4
    rendering(spec).raw_extension = b"extra"
    assert len(s108(report(spec))) == 1


def mp4(spec: B.IAMFSpec) -> bytes:
    """The fixture in MP4, one sample per temporal unit at its own frame length."""
    return wrap_mp4(B.build(spec), sample_duration=spec.num_samples_per_frame)


def test_object_fixture_reads_the_same_through_mp4():
    spec = B.object_spec(dual=True)
    a, b = report(spec), validate_bytes(mp4(spec))
    assert b.container == "mp4" and b.model.parse_errors == []
    assert rc_of(a) == rc_of(b)
    assert a.model.audio_elements[300].objects == b.model.audio_elements[300].objects
    assert s21x(a) == s21x(b) == []
    assert ([f.check_id for f in a.findings] == [f.check_id for f in b.findings]
            == ["S-303"])


def test_unreadable_extension_in_mp4_is_reported_once():
    # the descriptors are read twice on the MP4 path; one problem, one finding
    spec = B.object_spec()
    rendering(spec).raw_extension = b"\x01\x03\x01"
    assert len(s108(validate_bytes(mp4(spec)))) == 1


# ================================================================== S-210
@pytest.mark.parametrize("num_objects", [1, 2])
def test_object_count_one_or_two_silent(num_objects):
    assert_silent(report(B.object_spec(dual=num_objects == 2)))


def test_object_count_zero_fires():
    spec = B.object_spec()
    spec.elements[0].num_objects = 0
    r = report(spec)
    assert_only(r, "S-210", Severity.FAIL, "num_objects is 0")
    assert r.exit_code() == 1


@pytest.mark.parametrize("num_objects", [3, 255])
def test_object_count_above_two_is_a_warning_fires(num_objects):
    spec = B.object_spec()
    spec.elements[0].num_objects = num_objects
    r = report(spec)
    assert_only(r, "S-210", Severity.WARN, f"num_objects is {num_objects}",
                "gives a meaning to 1 and 2 only")
    if num_objects == 3:                 # 255 objects are also past the channel limit
        assert r.exit_code() == 0 and r.exit_code(Severity.WARN) == 1


def test_object_element_without_parameters_silent():
    r = report(B.object_spec())
    assert r.model.audio_elements[300].num_parameters == 0
    assert_silent(r)


@pytest.mark.parametrize("params,count", [([(1, 48000)], 1),
                                          ([(1, 48000), (2, 48000)], 2)])
def test_object_element_with_parameters_fires(params, count):
    spec = B.object_spec()
    spec.elements[0].params = params
    r = report(spec)
    assert r.model.audio_elements[300].num_parameters == count
    assert_only(r, "S-210", Severity.FAIL, f"num_parameters is {count}", "has to be 0")


@pytest.mark.parametrize("kind", ["channel", "scene"])
def test_parameters_rule_is_not_applied_to_other_element_types_silent(kind):
    spec = B.channel_spec("5.1") if kind == "channel" else B.scene_spec(1)
    spec.elements[0].params = [(1, 48000)]
    r = report(spec)
    assert r.model.audio_elements[300].num_parameters == 1
    assert_silent(r)


def test_object_element_with_one_substream_silent():
    r = report(B.object_spec(dual=True))
    assert r.model.audio_elements[300].num_substreams == 1
    assert_silent(r)


def test_object_element_with_two_substreams_is_a_warning_fires():
    spec = B.object_spec(dual=True)
    spec.elements[0].substream_ids = [0, 1]
    assert_only(report(spec), "S-210", Severity.WARN, "declares 2 audio substreams")


@pytest.mark.parametrize("profile,parse_errors", [(1, 0), (4, 1)])
def test_type_2_bytes_that_are_not_an_objects_config_are_not_judged(profile, parse_errors):
    # zero-size config, two substreams, a parameter, and a mix that gives the
    # element no position definition: the parser has said what is wrong (a
    # note, or S-108 under a v2.0.0 profile) and no object check guesses
    spec = B.object_spec(profile=profile)
    e = spec.elements[0]
    e.raw_config, e.substream_ids, e.params = b"\x00", [0, 1], [(1, 48000)]
    spec.mixes[0].rendering = {}
    r = report(spec)
    assert r.model.audio_elements[300].objects is None
    assert len(r.model.parse_errors) == parse_errors
    assert_silent(r)


# ============================================ reserved audio_element_type 3..7
@pytest.mark.parametrize("ae_type", [3, 4, 5, 6, 7])
def test_reserved_element_type_is_kept_noted_and_not_judged(ae_type):
    # Parsers are told to ignore the OBU, so nothing here is an error; the
    # element stays in the model so that its substreams and the mixes that
    # name it still resolve.
    spec = B.object_spec()
    e = spec.elements[0]
    e.audio_element_type, e.raw_config = ae_type, b"\x01\x00"
    e.substream_ids, e.params = [0, 1], [(1, 48000)]
    rendering(spec).params = [position(POLAR), position(DUAL_CART16)]
    r = report(spec)
    ae = r.model.audio_elements[300]
    assert ae.audio_element_type == ae_type and ae.objects is None
    assert ae.channel_layers == [] and ae.ambisonics is None
    assert (ae.num_substreams, ae.num_parameters) == (2, 1)
    assert r.model.parse_notes == [
        f"audio_element 300: type {ae_type} (reserved) config not modelled"]
    assert r.model.parse_errors == []
    assert len(rc_of(r).position_definitions) == 2        # read, not judged
    assert_silent(r)
    ids = {f.check_id for f in r.findings}
    assert not ids & {"S-106", "S-108", "S-205", "S-207"}, ids
    assert len(r.model.audio_frames) == 4                  # both substreams, two units


def test_reserved_element_type_is_shown_as_such_in_a_diff(tmp_path):
    from sentinel.diff import diff_files
    paths = []
    for ae_type in (None, 5):
        spec = B.object_spec()
        if ae_type is not None:
            spec.elements[0].audio_element_type = ae_type
            spec.elements[0].raw_config = b"\x01\x01"
        paths.append(tmp_path / f"type-{ae_type}.iamf")
        paths[-1].write_bytes(B.build(spec))
    res = diff_files(str(paths[0]), str(paths[1]))
    (entry,) = [e for e in res.structural_diffs if e.where == "audio_element[0]"]
    assert entry.a == "object/objects=1 sub=1 ids=[0]" and entry.b == "type5 sub=1"


# ================================================================== S-211
@pytest.mark.parametrize("ptype", SINGLE + DUAL)
def test_object_with_its_one_position_definition_silent(ptype):
    r = report(B.object_spec(dual=ptype in DUAL, ptype=ptype))
    assert rc_of(r).position_definitions[0].param_definition_type == ptype
    assert_silent(r)


@pytest.mark.parametrize("form", ["empty-envelope", "num-parameters-0"])
def test_object_without_a_position_definition_fires(form):
    spec = B.object_spec()
    rs = rendering(spec)
    rs.params, rs.write_num_parameters = [], form == "num-parameters-0"
    r = report(spec)
    assert rc_of(r).num_parameters == (0 if form == "num-parameters-0" else None)
    assert_only(r, "S-211", Severity.FAIL, "object-based element carries no position "
                "definition", "param_definition_type 3..8")
    assert r.exit_code() == 1


@pytest.mark.parametrize("kind", ["channel", "scene"])
def test_non_object_element_without_a_position_definition_silent(kind):
    assert_silent(report(B.channel_spec("5.1") if kind == "channel" else B.scene_spec(1)))


@pytest.mark.parametrize("kind", ["channel", "scene"])
@pytest.mark.parametrize("ptype", [POLAR, DUAL_CART8])
def test_non_object_element_with_a_position_definition_fires(kind, ptype):
    spec = B.channel_spec("5.1") if kind == "channel" else B.scene_spec(1)
    rendering(spec).params = [position(ptype)]
    assert_only(report(spec), "S-211", Severity.FAIL, f"{kind}-based element carries "
                f"a position definition ({TYPE_NAME[ptype]} ({ptype}))",
                "object-based elements only")


@pytest.mark.parametrize("ptype,name", [(0, "MIX_GAIN"), (1, "DEMIXING"),
                                        (2, "RECON_GAIN"), (9, "MOMENTARY_LOUDNESS")])
@pytest.mark.parametrize("kind", ["object", "channel"])
def test_other_defined_type_in_a_rendering_config_fires(ptype, name, kind):
    spec = B.object_spec() if kind == "object" else B.channel_spec("stereo")
    rendering(spec).params.append((ptype, b"\x00\x00"))
    assert_only(report(spec), "S-211", Severity.FAIL,
                f"carries param_definition_type {name} ({ptype})",
                "six position-based ones (3..8)")


def test_object_with_two_position_definitions_is_a_warning_fires():
    spec = B.object_spec()
    rendering(spec).params = [position(POLAR), position(CART8, parameter_id=2001)]
    r = report(spec)
    assert_only(r, "S-211", Severity.WARN, "carries 2 position definitions "
                "(POLAR (3), CART8 (4))", "asks for one")
    assert r.exit_code() == 0 and r.exit_code(Severity.WARN) == 1


def test_position_rule_reads_each_element_of_a_sub_mix_on_its_own():
    # object, stereo bed, object: the definitions belong to 300 and 302 only
    spec = B.object_spec()
    spec.elements += [
        B.ElementSpec(301, 0, "channel", [1], layers=[B.ChannelLayerSpec(1, 1, 1)]),
        B.ElementSpec(302, 0, "object", [2], num_objects=2)]
    spec.mixes[0].ae_ids = [300, 301, 302]
    rendering(spec, 302).params = [position(DUAL_POLAR)]
    assert_silent(report(spec))

    rendering(spec, 301).params = [position(POLAR)]       # on the bed
    rendering(spec, 302).params = []                      # missing on the object
    rendering(spec, 302).write_num_parameters = True
    r = report(spec)
    assert s21x(r) == [("S-211", Severity.FAIL)] * 2
    where = sorted(f.where for f in r.findings if f.check_id == "S-211")
    assert where == ["mix_presentation 42 / audio_element 301",
                     "mix_presentation 42 / audio_element 302"]


def test_position_rule_is_not_applied_to_a_missing_element():
    spec = B.object_spec()
    spec.mixes[0].ae_ids = [777]                          # S-106 reports the reference
    spec.mixes[0].rendering = {777: B.RenderingSpec(params=[position(POLAR)])}
    r = report(spec)
    assert "S-106" in {f.check_id for f in r.findings}
    assert_silent(r)


# ================================================================== S-212
@pytest.mark.parametrize("num_objects,ptype", [(1, t) for t in SINGLE]
                         + [(2, t) for t in DUAL])
def test_definition_for_the_right_object_count_silent(num_objects, ptype):
    assert_silent(report(B.object_spec(dual=num_objects == 2, ptype=ptype)))


@pytest.mark.parametrize("num_objects,ptype", [(1, t) for t in DUAL]
                         + [(2, t) for t in SINGLE])
def test_definition_for_the_wrong_object_count_fires(num_objects, ptype):
    spec = B.object_spec(dual=num_objects == 2)
    rendering(spec).params = [position(ptype)]
    placed = 3 - num_objects
    allowed = " / ".join(f"{TYPE_NAME[t]} ({t})" for t in (SINGLE if num_objects == 1
                                                           else DUAL))
    r = report(spec)
    assert_only(r, "S-212", Severity.FAIL,
                f"position definition {TYPE_NAME[ptype]} ({ptype}) places {placed} "
                f"object(s) but audio_element 300 has num_objects = {num_objects}",
                f"are {allowed}")
    assert r.exit_code() == 1


@pytest.mark.parametrize("ptype", SINGLE + DUAL)
def test_object_count_without_a_row_in_the_table_is_left_to_s210(ptype):
    # 3 objects: no definition is allowed, so none is called the wrong one
    spec = B.object_spec()
    spec.elements[0].num_objects = 3
    rendering(spec).params = [position(ptype)]
    assert_only(report(spec), "S-210", Severity.WARN, "num_objects is 3")


# ================================================================== S-213
@pytest.mark.parametrize("triple", [(-180, 0, 127), (180, 0, 0), (0, -90, 64),
                                    (0, 90, 64), (-180, -90, 0), (180, 90, 127)])
def test_polar_default_on_the_edge_of_its_range_silent(triple):
    spec = B.object_spec()
    rendering(spec).params = [position(POLAR, [triple])]
    assert_silent(report(spec))


@pytest.mark.parametrize("triple,words", [
    ((181, 0, 127), "default azimuth 181 is outside -180..180 degrees (a parser clips "
                    "it to 180)"),
    ((-181, 0, 127), "default azimuth -181 is outside -180..180 degrees (a parser "
                     "clips it to -180)"),
    ((255, 0, 127), "default azimuth 255"),
    ((-256, 0, 127), "default azimuth -256"),
    ((0, 91, 127), "default elevation 91 is outside -90..90 degrees (a parser clips it "
                   "to 90)"),
    ((0, -91, 127), "default elevation -91 is outside -90..90 degrees (a parser clips "
                    "it to -90)"),
    ((0, 127, 127), "default elevation 127"),
    ((0, -128, 127), "default elevation -128"),
])
def test_polar_default_past_its_range_fires(triple, words):
    spec = B.object_spec()
    rendering(spec).params = [position(POLAR, [triple], parameter_id=9)]
    r = report(spec)
    assert_only(r, "S-213", Severity.WARN, "position definition POLAR (parameter_id 9)",
                words)
    assert r.exit_code() == 0 and r.exit_code(Severity.WARN) == 1


def test_polar_default_names_the_object_and_every_value_fires():
    spec = B.object_spec(dual=True)
    rendering(spec).params = [position(DUAL_POLAR, [(0, 0, 127), (200, -100, 127)])]
    msg = assert_only(report(spec), "S-213", Severity.WARN,
                      "object 2 default azimuth 200", "object 2 default elevation -100")
    assert "object 1" not in msg


@pytest.mark.parametrize("ptype,triple", [(CART8, (-127, 127, -127)),
                                          (CART16, (-32767, 32767, -32767))])
def test_cartesian_default_on_the_cube_silent(ptype, triple):
    spec = B.object_spec(ptype=ptype)
    rendering(spec).params = [position(ptype, [triple])]
    assert_silent(report(spec))


@pytest.mark.parametrize("ptype,triple,words", [
    (CART8, (-128, 0, 0), "default x -128 normalises to -1.00787"),
    (CART8, (0, -128, 0), "default y -128 normalises to -1.00787"),
    (CART8, (0, 0, -128), "default z -128 normalises to -1.00787"),
    (CART16, (-32768, 0, 0), "default x -32768 normalises to -1.00003"),
    (CART16, (0, 0, -32768), "default z -32768 normalises to -1.00003"),
])
def test_cartesian_default_below_the_cube_fires(ptype, triple, words):
    spec = B.object_spec(ptype=ptype)
    rendering(spec).params = [position(ptype, [triple])]
    assert_only(report(spec), "S-213", Severity.WARN, words, "outside the -1.0..1.0 cube")


def test_cartesian_default_of_the_second_object_fires():
    spec = B.object_spec(dual=True, ptype=DUAL_CART16)
    rendering(spec).params = [position(DUAL_CART16, [(0, 0, 0), (0, -32768, 0)])]
    assert_only(report(spec), "S-213", Severity.WARN, "object 2 default y -32768")


# ================================================================== S-214
@pytest.mark.parametrize("gain", [("value", 0), ("value", -32768), ("value", 32767),
                                  ("range", -768, -1536, 0), ("range", 0, 0, 0),
                                  ("range", 256, -1, 1), ("range", -768, -32768, 32767)])
def test_element_gain_offset_of_a_defined_type_silent(gain):
    spec = B.channel_spec("stereo")
    rendering(spec).gain_offset = gain
    assert_silent(report(spec))


@pytest.mark.parametrize("gain_type", [2, 255])
def test_element_gain_offset_reserved_type_fires(gain_type):
    spec = B.object_spec()
    rs = rendering(spec)
    rs.gain_offset, rs.extension_bytes = (gain_type, b"\x01\x02\x03"), b"\xee"
    r = report(spec)
    assert_only(r, "S-214", Severity.WARN,
                f"element_gain_offset_type {gain_type} is reserved",
                "skips the 3 byte(s) that follow")
    rc = rc_of(r)                        # skipped by its size; the rest still read
    assert rc.element_gain_offset.extension_bytes == 3 and rc.extension_bytes == 1
    assert r.model.parse_errors == []


def test_element_gain_offset_range_with_a_positive_lower_bound_fires():
    spec = B.channel_spec("stereo")
    rendering(spec).gain_offset = ("range", -768, 1, 512)
    assert_only(report(spec), "S-214", Severity.WARN,
                "min_element_gain_offset is +0.00 dB", "regards a positive one as 0 dB")


def test_element_gain_offset_range_with_a_negative_upper_bound_fires():
    spec = B.channel_spec("stereo")
    rendering(spec).gain_offset = ("range", -768, -512, -256)
    assert_only(report(spec), "S-214", Severity.WARN,
                "max_element_gain_offset is -1.00 dB", "regards a negative one as 0 dB")


def test_element_gain_offset_range_with_both_bounds_inverted_fires():
    spec = B.channel_spec("stereo")
    rendering(spec).gain_offset = ("range", 0, 256, -256)
    r = report(spec)
    assert s21x(r) == [("S-214", Severity.WARN)] * 2
    assert r.exit_code() == 0 and r.exit_code(Severity.WARN) == 1


# ================================================================== S-215
@pytest.mark.parametrize("value", [0, 1, 2])
def test_defined_binaural_filter_profile_silent(value):
    spec = B.channel_spec("stereo")
    rendering(spec).binaural_filter_profile = value
    r = report(spec)
    assert rc_of(r).binaural_filter_profile == value
    assert_silent(r)


@pytest.mark.parametrize("kind", ["channel", "object"])
def test_reserved_binaural_filter_profile_fires(kind):
    spec = B.channel_spec("stereo") if kind == "channel" else B.object_spec()
    rendering(spec).binaural_filter_profile = 3
    r = report(spec)
    assert_only(r, "S-215", Severity.WARN, "binaural_filter_profile 3 is reserved",
                "0 (AMBIENT), 1 (DIRECT) and 2 (REVERBERANT)")
    assert r.exit_code() == 0 and r.exit_code(Severity.WARN) == 1


# ================================================================== S-216
@pytest.mark.parametrize("mode", [0, 1, 2])
def test_defined_headphones_rendering_mode_silent(mode):
    spec = B.channel_spec("stereo", profile=3)
    rendering(spec).headphones_rendering_mode = mode
    assert_silent(report(spec))


def test_reserved_headphones_rendering_mode_fires():
    spec = B.channel_spec("stereo")
    rendering(spec).headphones_rendering_mode = 3
    r = report(spec)
    assert_only(r, "S-216", Severity.WARN, "mix_presentation 42 is one that parsers of "
                "IAMF v2.0.0 are told to ignore",
                "audio_element 300 has the reserved headphones_rendering_mode 3")
    assert r.exit_code() == 0 and r.exit_code(Severity.WARN) == 1


@pytest.mark.parametrize("ptype", range(10))
def test_defined_parameter_definition_type_is_not_called_unknown(ptype):
    spec = B.object_spec()
    if ptype not in TYPE_NAME:
        rendering(spec).params.append((ptype, b""))       # S-211's business
    else:
        rendering(spec).params = [position(ptype)]        # S-212's, where it is wrong
    assert "S-216" not in {cid for cid, _sev in s21x(report(spec))}


@pytest.mark.parametrize("ptype", [10, 255, 300])
def test_unknown_parameter_definition_type_beside_a_position_fires(ptype):
    spec = B.object_spec()
    rendering(spec).params.append((ptype, b"\xaa\xbb"))
    r = report(spec)
    assert_only(r, "S-216", Severity.WARN, "told to ignore",
                f"rendering_config of audio_element 300 carries param_definition_type "
                f"{ptype}, which this version does not define")
    assert len(rc_of(r).position_definitions) == 1        # skipped by size, not lost


def test_unknown_type_in_place_of_the_position_is_not_also_a_missing_position():
    # It may be the position definition of a later version: reported as
    # unknown, and the element is not said to lack a position.
    spec = B.object_spec()
    rendering(spec).params = [(10, b"\x00\x00\x7f")]
    assert_only(report(spec), "S-216", Severity.WARN, "param_definition_type 10")


def test_one_finding_per_mix_presentation_naming_every_reason_fires():
    spec = B.object_spec()
    spec.elements.append(B.ElementSpec(301, 0, "channel", [1],
                                       layers=[B.ChannelLayerSpec(1, 1, 1)]))
    spec.mixes[0].ae_ids = [300, 301]
    rendering(spec, 300).params.append((11, b""))
    rendering(spec, 301).headphones_rendering_mode = 3
    spec.mixes.append(B.MixSpec(43, [301], "Bed Only", LAYOUTS))    # untouched
    r = report(spec)
    msg = assert_only(r, "S-216", Severity.WARN, "mix_presentation 42",
                      "audio_element 300 carries param_definition_type 11",
                      "audio_element 301 has the reserved headphones_rendering_mode 3")
    assert "mix_presentation 43" not in msg


def _with_redundant_descriptors(spec: B.IAMFSpec) -> bytes:
    """descriptors, frames, the same descriptors marked redundant, frames."""
    spec = spec.copy()
    frames = B._audio_frames(spec)
    spec.temporal_units = 0
    descriptors = B.build(spec)
    copy = bytearray(descriptors)
    p = 0
    while p < len(copy):                 # one-byte header, then leb128 obu_size
        copy[p] |= 0x04                  # obu_redundant_copy
        size, shift, q = 0, 0, p + 1
        while True:
            size |= (copy[q] & 0x7F) << shift
            shift += 7
            q += 1
            if not copy[q - 1] & 0x80:
                break
        p = q + size
    return descriptors + frames + bytes(copy) + frames


def test_rendering_findings_once_with_redundant_descriptor_copies_fires():
    spec = B.object_spec()
    rs = rendering(spec)
    rs.headphones_rendering_mode, rs.binaural_filter_profile = 3, 3
    rs.params = [position(DUAL_POLAR, [(200, 0, 0), (0, 0, 0)])]
    r = validate_bytes(_with_redundant_descriptors(spec))
    assert len(r.model.mix_presentations) == 2            # the model keeps every OBU
    assert sorted(s21x(r)) == [("S-212", Severity.FAIL), ("S-213", Severity.WARN),
                               ("S-215", Severity.WARN), ("S-216", Severity.WARN)]


# ================================================================== S-217
# The fixture codec is 24-bit LPCM: a whole frame of n samples is 3n bytes
# mono and 6n bytes stereo.
def _frames(spec: B.IAMFSpec, channels: int | None) -> B.IAMFSpec:
    spec.elements[0].frame_channels = channels
    return spec


def _frame_sizes(r) -> set[int]:
    frames = r.mp4.frame_refs if r.mp4 is not None else r.model.audio_frames
    return {f.frame_bytes for f in frames}


@pytest.mark.parametrize("container", ["raw", "mp4"])
@pytest.mark.parametrize("num_objects", [1, 2])
def test_object_frames_with_one_channel_per_object_silent(num_objects, container):
    spec = B.object_spec(dual=num_objects == 2)
    r = report(spec) if container == "raw" else validate_bytes(mp4(spec))
    assert _frame_sizes(r) == {8 * 3 * num_objects}       # judged, and right
    assert_silent(r)


@pytest.mark.parametrize("container", ["raw", "mp4"])
@pytest.mark.parametrize("num_objects", [1, 2])
def test_object_frames_of_the_other_channel_count_fires(num_objects, container):
    carried = 3 - num_objects
    spec = _frames(B.object_spec(dual=num_objects == 2), carried)
    r = report(spec) if container == "raw" else validate_bytes(mp4(spec))
    want = {1: "one channel (mono)", 2: "two channels (stereo)"}
    msg = assert_only(r, "S-217", Severity.FAIL,
                      f"num_objects is {num_objects}, so the element's audio substream "
                      f"has to be coded as {want[num_objects]}",
                      f"2 of its 2 LPCM frame(s) are {8 * 3 * carried} bytes: "
                      f"{want[carried]} of 8 samples at 24 bits")
    assert msg and r.exit_code() == 1
    (f,) = [f for f in r.findings if f.check_id == "S-217"]
    assert f.where == "audio_element 300 (object) / substream 0"
    assert (f.expected, f.found) == (f"{8 * 3 * num_objects} bytes per frame",
                                     f"{8 * 3 * carried} bytes")


def test_object_frame_length_is_read_past_a_padded_substream_id_fires():
    # audio_substream_id written as a 3-byte leb128: the frame is what follows
    # the id as coded, not the payload less one byte
    spec = _frames(B.object_spec(dual=True), 1)
    spec.temporal_units = 0
    frame = B.obu(5, b"\x80\x80\x00" + b"\x00" * 24)
    r = validate_bytes(B.build(spec) + frame + frame)
    assert [(f.substream_id, f.payload_len, f.frame_bytes)
            for f in r.model.audio_frames] == [(0, 27, 24)] * 2
    assert_only(r, "S-217", Severity.FAIL, "2 of its 2 LPCM frame(s) are 24 bytes")


def test_object_frame_length_on_an_implicit_id_frame_is_the_whole_payload():
    spec = B.object_spec(dual=True)
    spec.temporal_units = 0
    frame = B.obu(6, b"\x00" * 48)                         # OBU type 6: substream 0
    r = validate_bytes(B.build(spec) + frame)
    assert [(f.substream_id, f.frame_bytes) for f in r.model.audio_frames] == [(0, 48)]
    assert_silent(r)


@pytest.mark.parametrize("size", [8, 23, 25, 47, 49, 72])
def test_object_frame_that_is_neither_mono_nor_stereo_is_not_judged(size):
    # not a whole LPCM frame of either kind: what it is, is not this check's
    # to say (the 8-byte placeholder of the other fixtures is one such)
    spec = B.object_spec(dual=True)
    spec.temporal_units = 0
    frame = B.obu(5, b"\x00" + b"\x00" * size)
    assert_silent(validate_bytes(B.build(spec) + frame + frame))


def test_object_frames_of_another_codec_are_not_judged():
    # Opus frames are not fixed-size PCM; 24 bytes says nothing about channels
    spec = _frames(B.object_spec(dual=True), 1)
    spec.codec_id = "Opus"
    r = report(spec)
    assert r.model.codec_configs[0].codec_id == "Opus"
    assert_silent(r)


def test_channel_and_scene_frames_are_not_judged_by_the_object_rule():
    for spec in (B.channel_spec("stereo"), B.scene_spec(1)):
        spec.num_samples_per_frame = 8
        for e in spec.elements:
            e.frame_channels = 2                          # also on mono substreams
        assert_silent(report(spec))


def test_object_frames_without_any_frames_are_not_judged():
    spec = _frames(B.object_spec(dual=True), 1)
    spec.temporal_units = 0                               # descriptors only
    assert_silent(report(spec))


def test_object_frames_in_an_mp4_whose_samples_are_not_walked_are_not_judged():
    # As in a fragmented file: no samples in stsz, so there are no frames to
    # measure, and the same stream that fires above says nothing here.
    spec = _frames(B.object_spec(dual=True), 1)
    data = mp4(spec)
    assert s21x(validate_bytes(data)) == [("S-217", Severity.FAIL)]
    at = data.index(b"stsz") + 12                         # sample_count
    r = validate_bytes(data[:at] + (0).to_bytes(4, "big") + data[at + 4:])
    assert r.container == "mp4" and r.mp4.frame_refs == []
    assert r.model.audio_elements[300].objects.num_objects == 2
    assert_silent(r)


def test_object_frames_are_left_to_s210_when_the_count_or_substreams_are_off():
    spec = _frames(B.object_spec(), 2)                    # stereo frames
    spec.elements[0].num_objects = 3
    assert_only(report(spec), "S-210", Severity.WARN, "num_objects is 3")
    spec = _frames(B.object_spec(dual=True), 1)           # mono frames, two substreams
    spec.elements[0].substream_ids = [0, 1]
    assert_only(report(spec), "S-210", Severity.WARN, "declares 2 audio substreams")


def test_wrong_object_frames_among_right_ones_are_counted_fires():
    spec = B.object_spec()
    spec.temporal_units = 3                               # three mono frames
    stereo = B.obu(5, b"\x00" + b"\x00" * 48)
    assert_only(validate_bytes(B.build(spec) + stereo), "S-217", Severity.FAIL,
                "1 of its 4 LPCM frame(s) are 48 bytes")


# ===================================================== packs move severities
@pytest.mark.parametrize("check_id,build_spec", [
    ("S-213", lambda: _spec_with(lambda rs: setattr(
        rs, "params", [position(POLAR, [(200, 0, 127)])]))),
    ("S-215", lambda: _spec_with(lambda rs: setattr(rs, "binaural_filter_profile", 3))),
    ("S-216", lambda: _spec_with(lambda rs: setattr(rs, "headphones_rendering_mode", 3))),
])
def test_pack_can_promote_a_warning_to_a_fail(tmp_path, monkeypatch, check_id, build_spec):
    from sentinel import engine
    (tmp_path / "strict.toml").write_text(
        f'name = "strict"\n[severity]\n{check_id} = "FAIL"\n', encoding="utf-8")
    monkeypatch.setattr(engine, "PROFILE_DIR", str(tmp_path))
    r = validate_bytes(B.build(build_spec()), profile="strict")
    assert s21x(r) == [(check_id, Severity.FAIL)] and r.exit_code() == 1


def _spec_with(change) -> B.IAMFSpec:
    spec = B.object_spec()
    change(rendering(spec))
    return spec


# ================================================= shipped fixtures stay quiet
def test_shipped_fixtures_stay_clear_of_the_object_checks_silent():
    specs = B.all_valid_specs()
    assert {"object", "dual-object"} <= set(specs)
    for name, spec in specs.items():
        for data in (B.build(spec), mp4(spec)):
            r = validate_bytes(data)
            assert r.model.parse_errors == [], name
            assert s21x(r) == [], name


# ================================================== report surface and diff
def test_json_lists_object_elements_and_v2_rendering():
    from sentinel.report import render_json
    spec = B.object_spec(dual=True)
    rs = rendering(spec)
    rs.gain_offset, rs.binaural_filter_profile = ("range", -768, -1536, 0), 1
    stream = json.loads(render_json(report(spec)))["summary"]["stream"]
    assert stream["object_elements"] == [
        {"audio_element_id": 300, "num_objects": 2, "num_substreams": 1}]
    assert stream["rendering"] == [{
        "mix_presentation_id": 42, "sub_mix": 1, "audio_element_id": 300,
        "headphones_rendering_mode": 1, "binaural_filter_profile": "DIRECT",
        "position_definitions": [{
            "type": "DUAL_POLAR", "parameter_id": 2000,
            "defaults": [{"azimuth": 30, "elevation": 10, "distance": 127},
                         {"azimuth": -30, "elevation": 10, "distance": 127}]}],
        "element_gain_offset": {"type": "RANGE", "default_db": -3.0, "min_db": -6.0,
                                "max_db": 0.0}}]


def test_json_keeps_reserved_values_bare_and_names_defined_ones():
    from sentinel.report import render_json
    spec = B.object_spec(ptype=CART8)
    rs = rendering(spec)
    rs.binaural_filter_profile, rs.gain_offset = 3, (7, b"\x00")
    rs.params.append((12, b""))
    (entry,) = json.loads(render_json(report(spec)))["summary"]["stream"]["rendering"]
    assert entry["binaural_filter_profile"] == 3
    assert entry["element_gain_offset"] == {"type": 7}
    assert entry["other_param_definition_types"] == [12]
    assert entry["position_definitions"][0]["defaults"] == [{"x": -64, "y": 127, "z": 0}]


def test_json_stream_block_is_unchanged_for_a_v1_1_stream():
    from sentinel.report import render_json
    stream = json.loads(render_json(report(B.channel_spec("5.1"))))["summary"]["stream"]
    assert set(stream) == {"primary_profile", "codecs", "audio_elements",
                           "mix_presentations", "descriptor_bytes", "audio_frames"}


def test_text_and_html_show_the_object_and_rendering_facts():
    from sentinel.report import render_html, render_text
    spec = B.object_spec()
    rendering(spec).gain_offset = ("value", -768)
    r = report(spec)
    lines = render_text(r).splitlines()
    assert "  objects  : audio_element 300: 1 object" in lines
    assert ("  rendering: mix_presentation 42 / audio_element 300: POLAR position "
            "(parameter 2000), default azimuth 30 elevation 10 distance 127/127; "
            "element gain offset -3.00 dB") in lines
    html = render_html(r)
    assert "objects: audio_element 300: 1 object" in html
    assert "element gain offset -3.00 dB" in html

    plain = render_text(report(B.channel_spec("stereo")))
    assert "objects  :" not in plain and "rendering:" not in plain


def test_text_says_when_an_object_count_or_an_extension_was_not_read():
    from sentinel.report import render_text
    spec = B.object_spec(profile=1)
    spec.elements[0].raw_config = b"\x00"
    rendering(spec).raw_extension = b"extra"
    text = render_text(report(spec))
    assert "audio_element 300: object count unknown" in text
    assert "extension bytes not read (not IAMF v2.0.0 syntax)" in text


def _write(tmp_path, name: str, spec: B.IAMFSpec) -> str:
    path = tmp_path / name
    path.write_bytes(B.build(spec))
    return str(path)


def test_diff_sees_the_object_count_and_the_position_definition(tmp_path):
    from sentinel.diff import diff_files
    a = _write(tmp_path, "a.iamf", B.object_spec())
    b = _write(tmp_path, "b.iamf", B.object_spec(dual=True))
    res = diff_files(a, b)
    got = {e.where: (e.a, e.b) for e in res.structural_diffs}
    assert got == {
        "audio_element[0]": ("object/objects=1 sub=1 ids=[0]",
                             "object/objects=2 sub=1 ids=[0]"),
        "rendering mix[0] sub-mix[0] element[0]": (
            "POLAR default=30,10,127", "DUAL_POLAR default=30,10,127|-30,10,127")}
    assert res.exit_code() == 1


def test_diff_sees_a_moved_default_position_and_ignores_the_parameter_id(tmp_path):
    from sentinel.diff import diff_files
    base, same, moved = B.object_spec(), B.object_spec(), B.object_spec()
    rendering(same).params = [position(POLAR, parameter_id=5, rate=24000)]
    rendering(moved).params = [position(POLAR, [(31, 10, 127)])]
    a = _write(tmp_path, "a.iamf", base)
    assert diff_files(a, _write(tmp_path, "same.iamf", same)).verdict() == "IDENTICAL"
    res = diff_files(a, _write(tmp_path, "moved.iamf", moved))
    assert [(e.a, e.b) for e in res.structural_diffs] == [
        ("POLAR default=30,10,127", "POLAR default=31,10,127")]


def test_diff_sees_gain_offset_and_filter_profile_and_not_the_headphones_mode(tmp_path):
    from sentinel.diff import diff_files
    plain, v2, mode = (B.channel_spec("stereo") for _ in range(3))
    rs = rendering(v2)
    rs.gain_offset, rs.binaural_filter_profile = ("value", -768), 2
    rendering(mode).headphones_rendering_mode = 1
    a = _write(tmp_path, "a.iamf", plain)
    res = diff_files(a, _write(tmp_path, "v2.iamf", v2))
    assert [(e.where, e.a, e.b) for e in res.structural_diffs] == [
        ("rendering mix[0] sub-mix[0] element[0]", "(none)",
         "gain-offset type=0 [-768] binaural-filter-profile=2")]
    # a field v1.1.0 already had: comparing it now would change old verdicts
    assert diff_files(a, _write(tmp_path, "mode.iamf", mode)).verdict() == "IDENTICAL"
