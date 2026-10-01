"""OBU header bit 6 is read per OBU type, and every parse failure is visible.

IAMF v2.0.0 OBUHeader() gives the bit after obu_redundant_copy a per-type
meaning: obu_trimming_status_flag on audio frames (types 5..23),
optional_fields_flag on a Mix Presentation, is_not_key_frame on a Temporal
Delimiter, reserved on every other type. Only the trimming flag puts fields
after obu_size. Reading the bit as "trimming" on every type ate two leb128
values out of a Mix Presentation payload (the presentation was then dropped)
and out of the OBU following a non-key Temporal Delimiter (the walk stopped).

The second half is S-108: it used to fire only when a parse note happened to
contain one of three words, and the MP4 path threw away whatever its frame
re-walk met. A ParseError is now a finding whatever it says and wherever the
walk met it; forward-compat skips stay notes.

All bytes are synthesised by fixtures/ — no reference vectors are involved.
"""

from __future__ import annotations

import pytest

from fixtures import build as B
from fixtures.mp4wrap import wrap_mp4
from sentinel.engine import validate_bytes
from sentinel.findings import Severity
from sentinel.parser import parse_bytes

OLD_S108_WORDS = ("truncated", "exceeds", "smaller than")
PCM = b"\x00" * 8


def _ids(report, severity=None):
    return {f.check_id for f in report.findings
            if severity is None or f.severity == severity}


def _s108(report):
    return [f.message for f in report.findings if f.check_id == "S-108"]


def _descriptors(spec):
    """The descriptor OBUs alone, so a test can append hand-framed OBUs."""
    spec = spec.copy()
    spec.temporal_units = 0
    return B.build(spec)


# ------------------------------------------- Mix Presentation optional fields
def _optional_fields_spec(**kw):
    spec = B.channel_spec("stereo")
    spec.mixes[0].optional_fields = (0, 255)    # loudspeaker NONE, binaural reserved
    for k, v in kw.items():
        setattr(spec.mixes[0], k, v)
    return spec


def _assert_optional_fields_read(report, size=2):
    assert _ids(report, Severity.FAIL) == set(), [f.to_dict() for f in report.findings]
    assert report.model.parse_errors == []
    (mp,) = report.model.mix_presentations
    assert mp.mix_presentation_id == 42 and mp.annotations == ["Fixture Program"]
    assert mp.header.optional_fields_flag and not mp.header.trimming_status_flag
    assert (mp.header.num_samples_to_trim_at_end,
            mp.header.num_samples_to_trim_at_start) == (0, 0)
    assert mp.optional_fields_size == size
    assert (mp.preferred_loudspeaker_renderer, mp.preferred_binaural_renderer) == (0, 255)


def test_mix_presentation_optional_fields_raw():
    spec = _optional_fields_spec()
    raw = B.build(spec)
    mp_obu = B._mix_presentation(spec.mixes[0])
    assert mp_obu[0] == 0x12 and mp_obu in raw   # type 2 with bit 6 set
    r = validate_bytes(raw, source="optional-fields")
    _assert_optional_fields_read(r)
    assert len(r.model.audio_frames) == 2


def test_mix_presentation_optional_fields_mp4():
    r = validate_bytes(wrap_mp4(B.build(_optional_fields_spec())),
                       source="optional-fields-mp4")
    assert r.container == "mp4"
    _assert_optional_fields_read(r)
    assert len(r.mp4.frame_refs) == 2


def test_optional_fields_size_is_an_envelope():
    # tags before the optional fields, reserved bytes after the two known ones
    spec = _optional_fields_spec(tags=[("content_language", "eng")],
                                 optional_fields_remaining=b"\xaa\xbb\xcc")
    _assert_optional_fields_read(validate_bytes(B.build(spec), source="envelope"),
                                 size=5)


@pytest.mark.parametrize("size,expect", [
    (1, "optional_fields_size 1"),               # cannot hold the two known fields
    (9, "need 9 bytes, have 2"),                 # envelope overruns the OBU
])
def test_bad_optional_fields_size_is_a_parse_error(size, expect):
    spec = _optional_fields_spec()
    good = B._mix_presentation(spec.mixes[0])
    assert good[-3] == 2                         # optional_fields_size
    bad = good[:-3] + bytes([size]) + good[-2:]
    r = validate_bytes(B.build(spec).replace(good, bad), source=f"size-{size}")
    (msg,) = _s108(r)
    assert expect in msg
    # The Mix Presentation itself was read: a malformed tail is S-108, not S-105.
    assert len(r.model.mix_presentations) == 1
    assert not [f for f in r.findings if f.check_id == "S-105"]


# ------------------------------------------------ non-key Temporal Delimiters
NON_KEY = [1, 2, 4, 5]
FLAGS = [False, True, True, False, True, True]


def _non_key_spec():
    spec = B.channel_spec("5.1")                 # 4 substreams per temporal unit
    spec.temporal_units = 6
    spec.temporal_delimiters = True
    spec.non_key_tus = NON_KEY
    return spec


def test_non_key_temporal_delimiters_raw_all_frames_seen():
    raw = B.build(_non_key_spec())
    assert raw.count(b"\x22\x00") == len(NON_KEY)      # header 0x22, obu_size 0
    r = validate_bytes(raw, source="non-key")
    assert len(r.model.audio_frames) == 6 * 4
    assert _s108(r) == [] and r.model.parse_errors == []
    assert _ids(r, Severity.FAIL) == set()
    assert r.model.obu_order.count("TemporalDelimiter") == 6
    assert r.model.temporal_delimiter_is_not_key_frame == FLAGS


def test_non_key_temporal_delimiters_mp4_all_frames_seen():
    r = validate_bytes(wrap_mp4(B.build(_non_key_spec())), source="non-key-mp4")
    assert r.container == "mp4"
    assert len(r.mp4.frame_refs) == 6 * 4
    assert _s108(r) == []
    assert "S-408" not in _ids(r)                # no short frame count to misread
    assert _ids(r, Severity.FAIL) == set()
    assert r.mp4.temporal_delimiter_is_not_key_frame == FLAGS


# ------------------------------------------------- bit 6 on the other types
def test_trimming_still_read_on_every_audio_frame_type():
    # the range is types 5..23: explicit id, first implicit id, last implicit id
    frames = (B.obu(5, b"\x00" + PCM, trim_start=3)
              + B.obu(6, PCM, trim_end=7)
              + B.obu(23, PCM, trim_start=1, trim_end=2))
    mod = parse_bytes(_descriptors(B.channel_spec("stereo")) + frames)
    got = [(f.obu_type, f.substream_id, f.trim_start, f.trim_end, f.payload_len)
           for f in mod.audio_frames]
    assert got == [(5, 0, 3, 0, 9), (6, 0, 0, 7, 8), (23, 17, 1, 2, 8)]
    assert mod.parse_notes == []


def test_reserved_bit6_adds_no_header_fields():
    # type 24 is not an audio frame: the bit is reserved there and nothing
    # follows obu_size, so a zero-size OBU must not swallow its neighbour
    frames = B.obu(24, b"", flag=True) + B.obu(5, b"\x00" + PCM)
    mod = parse_bytes(_descriptors(B.channel_spec("stereo")) + frames)
    assert [(f.obu_type, f.payload_len) for f in mod.audio_frames] == [(5, 9)]
    assert mod.parse_errors == []


# ------------------------------------------------------------------- S-108
def _unterminated_annotation():
    """A well-framed Mix Presentation whose payload ends inside a string."""
    spec = B.channel_spec("stereo")
    good = B._mix_presentation(spec.mixes[0])
    payload = good[2:]                           # 1-byte header, 1-byte obu_size
    cut = 2 + len(b"en-us\x00") + 5              # inside "Fixture Program"
    return B.build(spec).replace(good, B.obu(2, payload[:cut]))


def test_parse_error_without_the_old_trigger_words_is_s108():
    r = validate_bytes(_unterminated_annotation(), source="unterminated")
    (msg,) = _s108(r)
    assert "unterminated string" in msg
    assert not any(word in msg for word in OLD_S108_WORDS)
    assert r.exit_code() == 1


def test_forward_compat_notes_are_not_findings():
    frames = B.obu(25, b"\x01\x02\x03") + B.obu(5, b"\x00" + PCM)
    r = validate_bytes(_descriptors(B.channel_spec("stereo")) + frames,
                       source="reserved-obu")
    assert any("unknown OBU type 25" in n for n in r.model.parse_notes)
    assert _s108(r) == []
    assert _ids(r, Severity.FAIL) == set()
    assert len(r.model.audio_frames) == 1


def test_mp4_sample_walk_parse_problem_is_s108():
    spec = B.channel_spec("stereo")
    spec.temporal_units = 4
    mp4 = bytearray(wrap_mp4(B.build(spec)))
    assert mp4[-11:-9] == b"\x28\x09"            # last audio frame: header, obu_size
    mp4[-10] = 0x7F                              # obu_size now overruns the sample
    r = validate_bytes(bytes(mp4), source="rewalk")
    (msg,) = _s108(r)
    assert msg.startswith("structural parse problem: MP4 samples (")
    assert "need 127 bytes, have 9" in msg
    assert len(r.mp4.frame_refs) == 3            # the walk stopped one frame short
    assert r.exit_code() == 1


def test_mp4_descriptor_parse_error_is_reported_once():
    # the re-walk reads the descriptors a second time; one problem, one finding
    r = validate_bytes(wrap_mp4(_unterminated_annotation()), source="once")
    (msg,) = _s108(r)
    assert "unterminated string" in msg and "MP4 samples" not in msg


# ----------------------------- reserved bit 6 where IAMF v2.0.0 keeps it at 0
# Sequence Header, Codec Config, Audio Element and Parameter Block have no
# meaning for the bit ("SHALL be set to 0"). Setting it is a parse error for
# S-108, and the OBU is still read: the bit adds no fields.
RESERVED_BIT6_MESSAGE = ("structural parse problem: reserved header bit 6 is set on "
                         "a {} OBU; IAMF v2.0.0 requires 0 (first at byte {})")


def _with_parameter_blocks(n: int = 1, bit6: bool = False) -> bytes:
    """A stereo stream with n Parameter Block OBUs between descriptors and frames."""
    spec = B.channel_spec("stereo")
    block = B.obu(3, B.Writer().leb128(1000).raw(b"\x00\x00").bytes(), flag=bit6)
    return _descriptors(spec) + block * n + B._audio_frames(spec)


def _obu_offsets(stream: bytes) -> dict[str, int]:
    """Offset of the first OBU of each modelled type in _with_parameter_blocks()."""
    mod = parse_bytes(stream)
    return {"SequenceHeader": mod.sequence_header.header.file_offset,
            "CodecConfig": mod.codec_configs[0].header.file_offset,
            "AudioElement": mod.audio_elements[300].header.file_offset,
            # the first Parameter Block follows the descriptors directly
            "ParameterBlock": len(_descriptors(B.channel_spec("stereo")))}


def _set_bit6(stream: bytes, offset: int) -> bytes:
    out = bytearray(stream)
    out[offset] |= 0x02
    return bytes(out)


def _shape(mod):
    """What the stream said, apart from the header bit under test."""
    return (mod.sequence_header.ia_code, mod.sequence_header.primary_profile,
            sorted(mod.codec_configs), sorted(mod.audio_elements),
            [mp.mix_presentation_id for mp in mod.mix_presentations],
            mod.parameter_block_ids, mod.obu_order,
            [(f.substream_id, f.payload_len) for f in mod.audio_frames])


def test_reserved_bit6_clear_is_silent():
    r = validate_bytes(_with_parameter_blocks(), source="bit6-clear")
    assert r.model.parse_errors == [] and _s108(r) == []
    assert r.model.parameter_block_ids == [1000]


@pytest.mark.parametrize("name", ["SequenceHeader", "CodecConfig", "AudioElement",
                                  "ParameterBlock"])
def test_reserved_bit6_set_is_s108_and_the_obu_is_still_read(name):
    clean = _with_parameter_blocks()
    offset = _obu_offsets(clean)[name]
    r = validate_bytes(_set_bit6(clean, offset), source="bit6-set")
    assert _s108(r) == [RESERVED_BIT6_MESSAGE.format(name, offset)]
    assert _shape(r.model) == _shape(parse_bytes(clean))
    assert r.exit_code() == 1


def test_reserved_bit6_is_reported_once_per_obu_type():
    stream = _with_parameter_blocks(n=3, bit6=True)
    offsets = _obu_offsets(stream)
    r = validate_bytes(_set_bit6(stream, offsets["CodecConfig"]), source="bit6-many")
    assert _s108(r) == [
        RESERVED_BIT6_MESSAGE.format("CodecConfig", offsets["CodecConfig"]),
        RESERVED_BIT6_MESSAGE.format("ParameterBlock", offsets["ParameterBlock"])]
    assert r.model.parameter_block_ids == [1000, 1000, 1000]


@pytest.mark.parametrize("obu_type", [24, 25, 30])
def test_reserved_bit6_on_obu_types_the_parser_skips_is_not_reported(obu_type):
    # 25 and 30 are reserved OBU types: a later version may give the bit a
    # meaning there, as v2.0.0 did for two existing types. 24 (Metadata) is
    # defined by v2.0.0 and its bit 6 is reserved, but this parser does not
    # read that OBU yet, so it stays a forward-compatibility skip for now.
    frames = B.obu(obu_type, b"\x01", flag=True) + B.obu(5, b"\x00" + PCM)
    r = validate_bytes(_descriptors(B.channel_spec("stereo")) + frames, source="skip")
    assert r.model.parse_errors == [] and _s108(r) == []
    assert len(r.model.audio_frames) == 1


def test_reserved_bit6_in_mp4_descriptors_is_reported_once():
    clean = B.build(B.channel_spec("stereo"))
    offset = _obu_offsets(_with_parameter_blocks())["CodecConfig"]
    r = validate_bytes(wrap_mp4(_set_bit6(clean, offset)), source="bit6-mp4")
    assert _s108(r) == [RESERVED_BIT6_MESSAGE.format("CodecConfig", offset)]
    assert len(r.mp4.frame_refs) == 2


# ------------------------------------------- MP4 samples that cannot be read
# extract_iamf_stream returns None both when there is nothing to rebuild from
# and when the sample tables cannot be followed. Only the second is an error,
# and it must not leave the report clean: the samples were never read.
def _four_tu_mp4() -> bytes:
    spec = B.channel_spec("stereo")
    spec.temporal_units = 4
    return wrap_mp4(B.build(spec))


def _patch_u32(mp4: bytes, fourcc: bytes, field_offset: int, value: int) -> bytes:
    """Overwrite one 32-bit field of a box, counted from its fourcc."""
    at = mp4.index(fourcc) + field_offset
    return mp4[:at] + value.to_bytes(4, "big") + mp4[at + 4:]


def test_mp4_with_every_sample_present_is_silent():
    from sentinel.container.mp4 import extract_iamf_stream, parse_mp4
    mp4 = _four_tu_mp4()
    r = validate_bytes(mp4, source="whole")
    assert _s108(r) == [] and r.mp4.sample_table_error is None
    assert len(r.mp4.frame_refs) == 4
    assert isinstance(extract_iamf_stream(mp4, parse_mp4(mp4)), bytes)


def test_mp4_truncated_inside_the_last_sample_is_s108():
    from sentinel.container.mp4 import extract_iamf_stream, parse_mp4
    mp4 = _four_tu_mp4()[:-3]
    r = validate_bytes(mp4, source="truncated")
    (msg,) = _s108(r)
    assert msg.startswith("structural parse problem: MP4 samples could not be read: "
                          "sample 3 of 4 is 11 bytes at offset ")
    assert msg.endswith(f"which runs past the end of the file ({len(mp4)} bytes)")
    assert r.mp4.frame_refs == [] and r.exit_code() == 1
    info = parse_mp4(mp4)
    assert extract_iamf_stream(mp4, info) is None       # the return value is unchanged
    assert info.sample_table_error == r.mp4.sample_table_error


def test_mp4_sample_tables_that_disagree_is_s108():
    mp4 = _patch_u32(_four_tu_mp4(), b"stsc", 16, 3)    # samples_per_chunk 4 -> 3
    r = validate_bytes(mp4, source="short-stsc")
    assert _s108(r) == ["structural parse problem: MP4 samples could not be read: stsz "
                        "declares 4 samples but stsc/stco place only 3 of them (1 chunk(s))"]
    assert r.exit_code() == 1


def test_mp4_hostile_stsc_run_is_bounded_by_the_chunk_table():
    # first_chunk is an untrusted u32. A later run that starts millions of
    # chunks ahead must not make the walker build a list that long: the
    # expansion is bounded by the chunks stco lists, and the tables then
    # simply disagree (S-108).
    import tracemalloc
    from sentinel.container.mp4 import extract_iamf_stream, parse_mp4
    mp4 = _four_tu_mp4()
    info = parse_mp4(mp4)
    track = next(t for t in info.tracks if t.has_iamf)
    assert extract_iamf_stream(mp4, info) is not None and len(track.chunk_offsets) == 1
    track.stsc = [(1, 1), (2_000_001, 17), (3, 3)]
    tracemalloc.start()
    try:
        assert extract_iamf_stream(mp4, info) is None
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 1_000_000, f"stsc run expansion allocated {peak} bytes"
    assert "place only 1 of them" in info.sample_table_error


def test_mp4_without_sample_tables_is_not_an_error():
    # As in a fragmented file: no samples in stsz, so nothing to rebuild from.
    from sentinel.container.mp4 import extract_iamf_stream, parse_mp4
    mp4 = _patch_u32(_four_tu_mp4(), b"stsz", 12, 0)    # sample_count 4 -> 0
    r = validate_bytes(mp4, source="no-tables")
    assert _s108(r) == [] and r.mp4.sample_table_error is None
    info = parse_mp4(mp4)
    assert extract_iamf_stream(mp4, info) is None and info.sample_table_error is None
