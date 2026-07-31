#!/usr/bin/env python3
"""Native side of the WASM differential: run engine.validate on /work/<name> copies.

Environment (all optional):
  SENTINEL_OSS   sentinel-oss tree root      (default: this file's ../)
  SENTINEL_PRO   sentinel-pro tree root      (for the youtube profile pack; parity
                 with the page, which embeds youtube.toml into the core zip)
  WASM_CORPUS    corpus root with valid/ + corrupt/   (default: $SENTINEL_OSS/corpus)
  WP1_SAMPLES / WP3_SAMPLES   real-sample dirs
  WASM_OUT       output dir for native_reports.json   (default: cwd)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OSS = os.environ.get('SENTINEL_OSS', os.path.dirname(HERE))
PRO = os.environ.get('SENTINEL_PRO')
sys.path.insert(0, OSS)
if PRO:
    sys.path.insert(0, PRO)
from sentinel.engine import validate            # noqa: E402
from sentinel.report import render_json         # noqa: E402

CORPUS = os.environ.get('WASM_CORPUS', os.path.join(OSS, 'corpus'))
WP1 = os.environ.get('WP1_SAMPLES', '/tmp/sentinel_build/wp1/wp1-samples')
WP3 = os.environ.get('WP3_SAMPLES', '/tmp/sentinel_build/wp3/wp3-samples')
OUT = os.environ.get('WASM_OUT', os.getcwd())

CASES = []  # (abs_path, profile)
for d in ('valid', 'corrupt'):
    dd = os.path.join(CORPUS, d)
    if os.path.isdir(dd):
        for f in sorted(os.listdir(dd)):
            CASES.append((os.path.join(dd, f), 'generic'))
for f in ('stereo_ffmpeg.iamf', 'stereo_iamftools.iamf', 'youtube_candidate_5dot1.mp4'):
    p = os.path.join(WP1, f)
    if os.path.exists(p):
        CASES.append((p, 'generic'))
for f in ('cd_bed_stereo.iamf', 'dlb_obj_static1.iamf'):
    p = os.path.join(WP3, f)
    if os.path.exists(p):
        CASES.append((p, 'generic'))
yt = os.path.join(WP1, 'youtube_candidate_5dot1.mp4')
if os.path.exists(yt):
    CASES.append((yt, 'youtube'))

os.makedirs('/work', exist_ok=True)
out = {}
for path, profile in CASES:
    name = os.path.basename(path)
    safe = ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)
    wp = '/work/' + safe
    shutil.copyfile(path, wp)
    r = validate(wp, profile=profile)
    out[f'{name}::{profile}'] = json.loads(render_json(r))

with open(os.path.join(OUT, 'native_reports.json'), 'w') as fh:
    json.dump(out, fh, indent=1, sort_keys=True)
print(f'{len(out)} native reports written')
