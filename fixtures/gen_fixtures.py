"""Write the deterministic fixture corpus + sample reports to disk.

    python -m fixtures.gen_fixtures [outdir]

Emits valid IAMF for every layout, a set of named corrupt files (incl. the
F4-class 7.1.4), and rendered json/text/html reports for the shipped samples.
Regenerates byte-identically every run (no randomness).
"""

from __future__ import annotations
import os
import sys

from . import build as B
from . import mutate as M
from sentinel.engine import validate
from sentinel.report import render


def write_corpus(outdir: str):
    valid_dir = os.path.join(outdir, "valid")
    corrupt_dir = os.path.join(outdir, "corrupt")
    os.makedirs(valid_dir, exist_ok=True)
    os.makedirs(corrupt_dir, exist_ok=True)

    for name, spec in B.all_valid_specs().items():
        with open(os.path.join(valid_dir, f"{name}.iamf"), "wb") as fh:
            fh.write(B.build(spec))

    # a curated, named corrupt set (one representative per class)
    named = {
        "f4_coupled_wrong_7_1_4": M._mut_coupled_wrong,
        "f4_wrong_layout_5_1_as_7_1_4": M._mut_wrong_layout_value,
        "f4_dropped_substream": M._mut_drop_substream_frames,
        "f4_duplicate_substream_id": M._mut_duplicate_substream_id,
        "f1_zero_parameter_rate": M._mut_zero_param_rate,
        "f7_loudness_zero_default": M._mut_loudness_zero_default,
        "f23_stereo_only_multichannel": M._mut_stereo_only_multichannel,
        "ambisonics_broken_acn": M._mut_ambi_mapping_dup,
        "dangling_codec_ref": M._mut_dangling_codec_ref,
        "truncated": M._mut_truncate,
    }
    for name, fn in named.items():
        with open(os.path.join(corrupt_dir, f"{name}.iamf"), "wb") as fh:
            fh.write(fn())
    return valid_dir, corrupt_dir


def write_sample_reports(outdir: str, sample_roots):
    rep_dir = os.path.join(outdir, "sample-reports")
    os.makedirs(rep_dir, exist_ok=True)
    samples = [
        ("stereo_iamftools.iamf", "generic"),
        ("stereo_ffmpeg.iamf", "generic"),
        ("cd_bed_stereo.iamf", "generic"),
        ("dlb_obj_static1.iamf", "generic"),
        ("youtube_candidate_5dot1.mp4", "youtube"),
    ]
    written = []
    for name, profile in samples:
        path = None
        for root in sample_roots:
            cand = os.path.join(root, name)
            if os.path.exists(cand):
                path = cand
                break
        if not path:
            continue
        r = validate(path, profile=profile)
        base = os.path.splitext(name)[0]
        for fmt, ext in (("text", "txt"), ("json", "json"), ("html", "html")):
            out = os.path.join(rep_dir, f"{base}.{ext}")
            with open(out, "w") as fh:
                fh.write(render(r, fmt))
            written.append(out)
    return rep_dir, written


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "corpus"
    sample_roots = [
        "/tmp/sentinel_build/wp1/wp1-samples",
        "/tmp/sentinel_build/wp3/wp3-samples",
    ]
    v, c = write_corpus(outdir)
    rep, files = write_sample_reports(outdir, sample_roots)
    print(f"valid fixtures  -> {v}")
    print(f"corrupt fixtures-> {c}")
    print(f"sample reports  -> {rep} ({len(files)} files)")
