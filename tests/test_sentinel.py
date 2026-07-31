"""Sentinel Phase-1 acceptance suite (PRD R1/R2/R6).

Run:  cd pkg && python -m pytest tests/ -q
Covers: real-sample parsing, clean-room round-trip, the F4-killer mutation
suite (>=99% detection / 0 false passes), fuzz no-crash, and the CI exit
contract.
"""

from __future__ import annotations
import os
import random
import sys

import pytest

HERE = os.path.dirname(__file__)
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from sentinel.engine import validate, validate_bytes           # noqa: E402
from sentinel.parser import parse_bytes                          # noqa: E402
from sentinel.findings import Severity, REGISTRY                 # noqa: E402
from fixtures.build import all_valid_specs, build, channel_spec  # noqa: E402
from fixtures.mutate import run_suite, MUTATIONS                 # noqa: E402

# Sample corpus roots (present in the WP1/WP3 artifact extraction; the f31
# root carries the FFmpeg trim-carriage evidence files from f31-artifacts.zip).
SAMPLE_ROOTS = [
    "/tmp/sentinel_build/wp1/wp1-samples",
    "/tmp/sentinel_build/wp3/wp3-samples",
    "/tmp/sentinel_build/f31/f31-samples",
]


def _sample(name):
    for root in SAMPLE_ROOTS:
        p = os.path.join(root, name)
        if os.path.exists(p):
            return p
    pytest.skip(f"sample {name} not available")


# --------------------------------------------------------------------- L1 parse
@pytest.mark.parametrize("name,profile,codec,elements", [
    ("stereo_iamftools.iamf", "Simple", "Opus", 1),
    ("stereo_ffmpeg.iamf", "Simple", "Opus", 1),
    ("cd_bed_stereo.iamf", "Base", "ipcm", 1),
    ("dlb_obj_static1.iamf", "Base", "ipcm", 1),
])
def test_real_samples_parse(name, profile, codec, elements):
    from sentinel import model as m
    data = open(_sample(name), "rb").read()
    mod = parse_bytes(data)
    assert mod.sequence_header.ia_code == "iamf"
    assert m.PROFILE_NAME[mod.sequence_header.primary_profile] == profile
    assert codec in {cc.codec_id for cc in mod.codec_configs.values()}
    assert len(mod.audio_elements) == elements
    assert not any("truncated" in n for n in mod.parse_notes)


def test_iamftools_stereo_is_clean():
    r = validate(_sample("stereo_iamftools.iamf"))
    assert r.passed(), [f.to_dict() for f in r.findings if f.severity == Severity.FAIL]
    assert r.exit_code() == 0


def test_ffmpeg_zero_loudness_fails_f7():
    r = validate(_sample("stereo_ffmpeg.iamf"))
    ids = {f.check_id for f in r.findings if f.severity == Severity.FAIL}
    assert "S-301" in ids            # F7 unmeasured 0.0 default
    assert r.exit_code() == 1


def test_dolby_scene_flags_f23_stereo_only_loudness():
    r = validate(_sample("dlb_obj_static1.iamf"))
    ids = {f.check_id for f in r.findings}
    assert "S-302" in ids            # F23 stereo-only loudness for 16-ch scene
    assert "S-208" in ids            # F24 template annotation


def test_cd_bed_template_name_f24():
    r = validate(_sample("cd_bed_stereo.iamf"))
    assert "S-208" in {f.check_id for f in r.findings}


# ------------------------------------------------------------------ MP4 + profile
def _require_profile(name):
    """Skip when a platform profile pack isn't available (packs beyond
    `generic` ship with iamf-sentinel-pro — D1 seam, PLUGIN_SEAM.md)."""
    from sentinel.engine import load_profile
    try:
        load_profile(name)
    except FileNotFoundError:
        pytest.skip(f"profile pack {name!r} not installed (iamf-sentinel-pro)")


def test_youtube_candidate_passes_youtube_profile():
    _require_profile("youtube")
    r = validate(_sample("youtube_candidate_5dot1.mp4"), profile="youtube")
    assert r.container == "mp4"
    assert r.passed(), [f.to_dict() for f in r.findings if f.severity == Severity.FAIL]
    # F12 codec-string casing surfaced as a WARN
    assert "S-403" in {f.check_id for f in r.findings}


def test_mp4_extracts_5dot1_descriptor():
    r = validate(_sample("youtube_candidate_5dot1.mp4"))
    ae = next(iter(r.model.audio_elements.values()))
    assert ae.num_substreams == 4 and ae.channel_layers[0].coupled_substream_count == 2


# ------------------------------------------------------------- round-trip / valid
@pytest.mark.parametrize("name", list(all_valid_specs().keys()))
def test_valid_fixtures_pass_clean(name):
    spec = all_valid_specs()[name]
    r = validate_bytes(build(spec), source=name)
    fails = [f.check_id for f in r.findings if f.severity == Severity.FAIL]
    assert fails == [], fails
    assert r.passed()


# ------------------------------------------------- trim carriage (F31, §6.2.2)
def _opus_spec(**kw):
    spec = channel_spec("stereo")
    spec.codec_id = "Opus"           # fixture Codec Config carries pre_skip 312
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _trim_ids(r):
    return {f.check_id for f in r.findings if f.check_id in ("S-407", "S-408", "S-409")}


def test_trim_fields_retained_in_model():
    # §1.1 cause 2: the parser read the trim fields but the model dropped them.
    mod = parse_bytes(build(_opus_spec(trim_start_first_tu=312, trim_end_last_tu=100)))
    first_tu = [fr for fr in mod.audio_frames if fr.first_temporal]
    assert first_tu and all(fr.trim_start == 312 for fr in first_tu)
    assert mod.audio_frames[-1].trim_end == 100


def test_elst_parsed_from_mp4():
    from fixtures.mp4wrap import wrap_mp4
    r = validate_bytes(wrap_mp4(build(_opus_spec(trim_start_first_tu=312)),
                                elst=[(648, 312)]), source="elst")
    track = next(t for t in r.mp4.tracks if t.has_iamf)
    assert track.edts_present and track.elst_entries == [(648, 312, 1)]


def test_mp4_trimmed_with_correct_elst_is_clean():
    from fixtures.mp4wrap import wrap_mp4
    r = validate_bytes(wrap_mp4(build(_opus_spec(trim_start_first_tu=312)),
                                elst=[(648, 312)]), source="valid-trim")
    assert _trim_ids(r) == set()
    assert not [f for f in r.findings if f.severity == Severity.FAIL]


def test_mp4_trim_without_elst_fails_s407():
    from fixtures.mp4wrap import wrap_mp4
    r = validate_bytes(wrap_mp4(build(_opus_spec(trim_start_first_tu=312))),
                       source="no-elst")
    assert "S-407" in {f.check_id for f in r.findings if f.severity == Severity.FAIL}


def test_mp4_elst_media_time_mismatch_fails_s407():
    from fixtures.mp4wrap import wrap_mp4
    r = validate_bytes(wrap_mp4(build(_opus_spec(trim_start_first_tu=312)),
                                elst=[(648, 120)]), source="elst-mismatch")
    assert "S-407" in {f.check_id for f in r.findings if f.severity == Severity.FAIL}


def test_mp4_stts_ignoring_end_trim_warns_s408():
    from fixtures.mp4wrap import wrap_mp4
    r = validate_bytes(wrap_mp4(build(_opus_spec(trim_start_first_tu=312,
                                                 trim_end_last_tu=100)),
                                elst=[(860, 312)]), source="stts-endtrim")
    assert _trim_ids(r) == {"S-408"}


def test_stripped_trim_fingerprint_warns_s409_raw_and_mp4():
    from fixtures.mp4wrap import wrap_mp4
    raw = build(_opus_spec())        # pre_skip 312, no trimming fields anywhere
    assert _trim_ids(validate_bytes(raw, source="raw-stripped")) == {"S-409"}
    r = validate_bytes(wrap_mp4(raw, elst=[(960, 0)]), source="mp4-stripped")
    assert _trim_ids(r) == {"S-409"}


def test_ipcm_streams_never_fingerprinted():
    # no codec delay -> S-409 must stay silent on every valid ipcm fixture
    for name, spec in all_valid_specs().items():
        assert _trim_ids(validate_bytes(build(spec), source=name)) == set(), name


def test_f31_ffmpeg_remux_flagged():
    # the doc-57 defective file: FFmpeg -c copy stripped 21 bytes of trim
    r = validate(_sample("ffmpeg-remux.mp4"))
    assert _trim_ids(r) == {"S-408", "S-409"}


def test_f31_ffmpeg_raw_copy_flagged():
    r = validate(_sample("roundtrip.iamf"))
    assert _trim_ids(r) == {"S-409"}


def test_f31_ffmpeg_encode_path_clean():
    # ADR-1's encode-from-WAV route writes the trim correctly — must stay clean
    r = validate(_sample("ffmpeg-encoded.iamf"))
    assert _trim_ids(r) == set()


# -------------------------------------------------------------- the F4 killer
def test_mutation_suite_detection_and_no_false_pass():
    results, rate = run_suite()
    misses = [label for label, expect, ok, fired in results if not ok]
    assert misses == [], f"undetected mutations (false passes): {misses}"
    assert rate >= 0.99


@pytest.mark.parametrize("mut", MUTATIONS, ids=[m.label for m in MUTATIONS])
def test_each_mutation_detected(mut):
    r = validate_bytes(mut.build_fn(), source=mut.label)
    assert mut.expect in {f.check_id for f in r.findings}


# ------------------------------------------------------------------- fuzz safety
def test_truncations_never_crash():
    for name, spec in all_valid_specs().items():
        data = build(spec)
        for n in range(len(data)):
            r = validate_bytes(data[:n], source=f"{name}:trunc{n}")
            assert r.execution_error is None, (name, n, r.execution_error)


def test_random_corruption_never_crashes():
    rng = random.Random(20260721)     # fixed seed: deterministic
    specs = list(all_valid_specs().values())
    for _ in range(4000):
        data = bytearray(build(rng.choice(specs)))
        for _ in range(rng.randint(1, 6)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        r = validate_bytes(bytes(data), source="rand")
        assert r.execution_error is None, r.execution_error


# --------------------------------------------------------------- CI exit contract
def test_exit_codes():
    good = validate_bytes(build(channel_spec("stereo")))
    assert good.exit_code() == 0
    bad = channel_spec("7.1.4")
    bad.elements[0].layers[0].coupled_substream_count = 4
    assert validate_bytes(build(bad)).exit_code() == 1
    err = validate("/no/such/file.iamf")
    assert err.exit_code() == 2


def test_strict_promotes_warn_to_fail():
    # a valid multichannel with template-free names but WARN-only findings
    spec = channel_spec("stereo")
    spec.mixes[0].annotation = "test_mix_pres"       # forces an S-208 WARN
    r = validate_bytes(build(spec), fail_on=Severity.WARN)
    assert r.exit_code() == 1


def test_registry_ids_are_unique_and_well_formed():
    assert len(REGISTRY) == len({c.id for c in REGISTRY.values()})
    for cid, c in REGISTRY.items():
        assert cid.startswith("S-") and c.title and c.layer


# ------------------------------------------------------------------ diff (R7)
def test_diff_structurally_equal_loudness_differs():
    from sentinel.diff import diff_files
    res = diff_files(_sample("stereo_iamftools.iamf"), _sample("stereo_ffmpeg.iamf"))
    assert res.structural_diffs == []            # same Stereo topology
    assert res.loudness_diffs                     # -18.84 vs 0.0 default
    assert res.exit_code() == 0


def test_diff_identical_self():
    from sentinel.diff import diff_files
    res = diff_files(_sample("cd_bed_stereo.iamf"), _sample("cd_bed_stereo.iamf"))
    assert res.verdict() == "IDENTICAL" and res.exit_code() == 0


def test_diff_different_topology(tmp_path):
    from sentinel.diff import diff_files
    a = tmp_path / "stereo.iamf"; a.write_bytes(build(channel_spec("stereo")))
    b = tmp_path / "surround.iamf"; b.write_bytes(build(channel_spec("7.1.4")))
    res = diff_files(str(a), str(b))
    assert res.structural_diffs and res.exit_code() == 1


# ------------------------------------------------------------------ batch (R9)
def test_batch_directory_rollup(tmp_path):
    from fixtures.build import all_valid_specs
    from sentinel.cli import _iter_media
    for name, spec in all_valid_specs().items():
        (tmp_path / f"{name}.iamf").write_bytes(build(spec))
    bad = channel_spec("5.1"); bad.elements[0].layers[0].coupled_substream_count = 3
    (tmp_path / "bad.iamf").write_bytes(build(bad))
    files = list(_iter_media(str(tmp_path)))
    assert len(files) == len(all_valid_specs()) + 1
    results = {f: validate(f).exit_code() for f in files}
    assert any(v == 1 for v in results.values())          # the bad file fails
    assert sum(1 for v in results.values() if v == 0) == len(all_valid_specs())
