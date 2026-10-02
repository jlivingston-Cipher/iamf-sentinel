# Failure-mode → Sentinel check traceability (F1–F34)

The WP1/WP3 failure catalogue is Sentinel's requirements seed and acceptance
test (PRD Goal 1: "the catalogue is the acceptance test"). Every entry is
classified below as: **file-detectable** (a check fires — ✅ Phase 1
descriptor-level, ✅ **Phase 2** L3 rendered), or **out of scope for a content
validator** (a build-environment, encode-time, or runtime issue that is not a
property of a produced IAMF file — several of these belong to the packager
"Loom" or a pre-flight ADM validator, not to Sentinel).

The **Symptom** column records each failure mode as it was catalogued,
against the tool versions tested at the time; it is not a statement about
upstream as it is today. Where upstream has moved since, the state as read
on 2026-10-01 is in *Upstream status* below.

Status is proven by the shipped test suites — real samples, the regenerated F4
essence-misroute pair, the full mutation battery, and a bounded-fuzz acceptance
pass; see the per-repo CI gates for the current figures. **Phase 2 (executed,
doc 19) closed the L3 column**: the S-31x/
S-32x checks run the reference decoders as subprocess oracles with Sentinel's
own BS.1770-4 measurement.

| F | Symptom (short) | Sentinel status | Check(s) | Notes |
|---|---|---|---|---|
| **F1** | `parameter_rate` required per parameter_id | ✅ Phase 1 | **S-204** | Flags `parameter_rate == 0` in any param definition. |
| **F2** | Ambisonics scene syntax (mode/layer) undocumented | ✅ Phase 1 | **S-203** | Validates ambisonics config well-formedness in the bitstream. |
| **F3** | Scene needs explicit ambisonic layout; SN3D assumed | ◑ Partial | **S-203** | ACN/(N+1)² completeness checked; SN3D-vs-N3D normalization is not bitstream-detectable (documented limitation). |
| **F4** | **Silent channel corruption on wrong substream order** | ✅ Phase 1 (structural) + ✅ **Phase 2 (essence)** | **S-201, S-202, S-205, S-207** + **S-320/S-321** | Topology/drop/duplicate mismatches are Phase-1 FAILs. The pure essence-misroute variant (identical descriptor, scrambled PCM) is now caught at L3: executed on the regenerated WP1 wrong-order 7.1.4 — S-321 flags the fabricated coupled pairs (r=1.0000); `diff --render` vs the correct twin exits 1. Beds-only precondition (scene renders legitimately correlate). |
| **F5** | *(REFUTED doc 56 — our invocation error; #23935 closed invalid, confirmed doc 63)* FFmpeg n8.1.2 remuxes IAMF correctly when `-stream_group map=` carries its non-optional `st=` arguments | ⛔ Withdrawn | — | Never a file property. ADR-2's remux-via-MP4Box decision stands on the F31/F32 repairability asymmetry (doc 61 §2), not on F5. |
| **F6** | `Duplicate id 0` when muxing with video | ⛔ Out of scope | — | Encode-time CLI error; never present in a validly produced file. |
| **F7** | Loudness 0.0 default written silently | ✅ Phase 1 + ✅ Phase 2 | **S-301** + **S-310/S-311** | Descriptor default → S-301 FAIL; the *measured* half is now executed: S-310 reports measured −18.85 vs declared 0.0 on the same file. |
| **F8** | `iamfdec` `-o3` + zero-frame "success" | ⛔ Out of scope | — | Decoder-CLI orchestration quirk; informs L3 oracle robustness (judge by output size, Phase 2). |
| **F9** | MP4Box DTS-patch (first TU duplicate timestamp) | ✅ Phase 1+2 | **S-206** + **S-405** | First-TU coverage (Phase 1) plus full stts/ctts walk (Phase 2): zero-delta entries and stts-vs-mdhd drift flagged. Executed: the shipped MP4Box output carries no residue (S-405 silent). |
| **F10** | libiamf offline build interventions | ⛔ Out of scope | — | Build environment (ADR-6). |
| **F11** | iamf-tools Bazel-only / unbuildable | ⛔ Out of scope | — | Build environment; CMake port (ADR-6). |
| **F12** | RFC6381 case mismatch (`opus` vs `Opus`) | ✅ Phase 1 | **S-403** | Derives canonical `iamf.PPP.AAA.<4CC>` and flags lowercasing. Proven on the YouTube MP4. |
| **F13** | Distro FFmpeg lag (no IAMF) | ⛔ Out of scope | — | Build environment. |
| **F14** | SIGSEGV: Dolby bed-only enhanced / 4-top | ⛔ Input-side | — | Encoder crash on **ADM input**; Sentinel validates IAMF **output**. Belongs to a pre-flight ADM validator / Loom refuse-list (packager PRD §5.2). |
| **F15** | SIGABRT: automation-grid sample underflow | ⛔ Input-side | — | Encoder crash on ADM input. Same as F14. |
| **F16** | audioObject `<gain>` aborts encode | ⛔ Input-side / ✅ Phase 3 aftermath | S-330 | Encoder abort on ADM input (same as F14); where a gain nonetheless vanishes into a produced file, `adm-compare` sees the trajectory divergence. |
| **F17** | `--adm_importance_threshold` ineffective | ✅ Phase 3 (`adm-compare`) | S-331 | Matched-filter presence of the below-threshold objects' rendered residual (unfiltered−filtered EAR reference) in the output — gain-invariant. Needs the source ADM (source-referenced mode, not single-file validate). |
| **F18** | Block-level `<gain>` silently discarded | ✅ Phase 3 (`adm-compare`) | S-330 | Windowed level-trajectory divergence (monotone drift) between EAR source render and oracle output render. Needs the source ADM. |
| **F19** | Spherical coords zeroed → origin collapse +6 dB | ✅ Phase 2 (signature) | **S-322**, S-304/**S-314** | Origin-collapse signature on decoded PCM (energy vector pinned to equal-energy baseline ∧ near-total channel correlation) + measured clipping via S-314. Exact-position verification still needs the source (transpiler QC). |
| **F20** | Position-less bed → origin collapse, clips | ✅ Phase 2 (signature) | **S-322**, **S-314** | Same executed signature + measured decoded-PCM peaks. |
| **F21** | 3OA fold: no level management → clipping | ✅ Phase 1+2 | **S-304** + **S-314** | Declared-peak WARN (Phase 1) plus measured true/digital peak on every rendered layout (Phase 2). |
| **F22** | Fixed `/tmp` temp filenames (concurrency) | ⛔ Out of scope | — | Runtime/process hazard; belongs to Loom's execution layer. |
| **F23** | Dolby-mode mix presentation: stereo-only loudness | ✅ Phase 1 | **S-302** | Multichannel/scene program with stereo-only loudness → WARN. Proven on `dlb_obj_static1.iamf`. |
| **F24** | ADM names/labels dropped; template annotations | ✅ Phase 1 | **S-208** | Template/placeholder annotation → WARN. Proven on cd-bed + Dolby samples. |
| **F25** | (Positive) authored loudness replaced by measurement | ℹ Informational | (**S-301/S-303**) | Not a defect; documented survival rule. |
| **F26** | `iamfdec` two-step build addendum | ⛔ Out of scope | — | Build environment; scripted in `build_toolchain.sh`. |

## New Phase-2 entries (executed; full detail in doc 19)

| F | Symptom (short) | Sentinel status | Check(s) | Notes |
|---|---|---|---|---|
| **F27** | Declared digital peak is pre-codec; decoded output exceeds it (+3.46 dB measured, Opus 7.1.4) | ✅ Phase 2 | **S-311** | Declared peak is not a decoded-peak bound; loudness survives coding (Δ0.000 LU) but peaks do not. |
| **F28** | *(as catalogued, against libiamf v1.1.0 and the iamf-tools pin of that date; the iamfdec half is no longer current upstream — see Upstream status)* Neither reference decoder decodes the A/V MP4 deliverable (decoder_main raw-only; iamfdec `-i1` SIGSEGV on video hdlr) | ✅ Phase 2 (worked around) | — | Sentinel extracts the raw IAMF stream clean-room from the sample tables and oracles that. Disclosure-grade (iamfdec crash). |
| **F29** | *(re-adjudicated docs 64/65 — FFmpeg defect, not a convention split; as catalogued, and still so at the FFmpeg n8.1.3 release tag; the top-back half is no longer current on FFmpeg master — see Upstream status)* ffmpeg `ebur128`'s BACK_MASK weights rears **and top-backs** 1.41 where BS.1770-4 Tables 4/5 say 1.00 (+1.5 LU per over-weighted channel, ≈+0.6 LU aggregate on equal-level 7.1.4 — doc 66 §4); iamf-tools is Table-conformant 12/12 | ✅ Phase 2, tables corrected by **F33** (doc 69) | S-310 | Sentinel measures with the BS.1770-4 tables directly (matching the declared-value producer by construction); `FFMPEG_WEIGHTS` kept solely to model ffmpeg's behaviour (as released) for cross-checks. QC-ing IAMF with ffmpeg at tight tolerance flags correct files. **FILED 2026-07-31 as FFmpeg/FFmpeg#23968** (`code.ffmpeg.org` tracker issue, doc 94; currency re-verified on master `5f832b7`, duplicate re-search CLEAR on both trackers with positive controls, docs 66/94), with a patch offered for either scope (minimal: drop `AV_CH_TOP_BACK_*` from `BACK_MASK`; full: key weights on BS.1770 Table 5 positions). **Closed 2026-08-06 — see Upstream status (as read 2026-10-01).** |
| **F33** | *(internal, found doc 66 §5, fixed doc 69)* Sentinel's own primary 7.1/7.1.2/7.1.4 tables carried rears (M±135) at 1.41 — the F29 defect class in our own tree, fossilized behind a comment citing a premise doc 64 refuted | ✅ **FIXED** (doc 69): dsp.py + C++ kernel, differential 15/15, regression pin `test_channel_weights_bs1770_conformance` | S-310 (feeds) | Round-trip pin moved −8.688 → −8.974 (weighted path only; unweighted −9.12 unmoved). Heights were always correct; 5.1-family tables were always conformant. **Cross-ecosystem (2026-08-04): also found + fixed independently in Inseglet 1.5.1 (the same author's REAPER MCP extension) — its bed table carried the same M±135 over-weight AND a second boundary cell this fix did not surface: wides Lw/Rw (M±060, 9.1.6, boundary-inclusive) at 1.00 where Table 5 says 1.41. Its `unit.bed_weights` pin mirrors sentinel-pro's conformance vectors as a hard-coded second witness. |
| **F34** | *(internal, found doc 69 §4 — unmasked by the F33 fix, defect pre-existing)* Loom's ffmpeg one-shot backend injected **ebur128-measured** declared loudness; on 7.1.x layouts those values carried F29's over-weighting (measured −0.554 LU on the parity content) — the emitted file was non-conformant and S-310 correctly FAILed it under the Loom gate | ✅ **FIXED** (doc 70): every Loom `measure_bs1770` step reroutes to the `sentinel-dsp` kernel (one argv, one JSON, all three figures); xfails removed, Loom 235/0; post-fix measured-vs-declared ≤0.005 LU on both oracles | S-310 (detects) | Invisible pre-F33 because Sentinel's own error partially cancelled ffmpeg's (top-backs-only residual ≈0.29 LU < ±0.5). Covers inject AND normalize AND preview paths by construction (the measure step is the reroute point). iamf-tools backend was never affected. `loom 0.8.0`. |

## New Phase-3c entries (trim carriage — docs 57/58, executed this cycle)

| F | Symptom (short) | Sentinel status | Check(s) | Notes |
|---|---|---|---|---|
| **F31** | *(as catalogued 2026-07; no longer current upstream — see Upstream status)* FFmpeg's IAMF `-c copy` silently strips `num_samples_to_trim_at_start` from the Audio Frame OBUs and writes `elst media_time=0` — value irrecoverable, no warning at any log level (release pin **and** master of that date) | ✅ Phase 3c | **S-407, S-408, S-409** | S-407: OBU trim present but edts/elst missing or `media_time` ≠ Σ start-trim (IAMF v1.1.0 §6.2.2 **SHALL**). S-408: Σstts ≠ TUs×nspf − end-trim (§6.2.2 duration model). S-409: Opus `pre_skip` > 0 with no trim fields anywhere — the remux fingerprint, raw or MP4. Executed on the doc-57 evidence files: `ffmpeg-remux.mp4` → S-408+S-409; raw `-c copy` → S-409; the encode path stays clean (ADR-1 unaffected). |
| **F32** | *(adjudicated doc 60 — GPAC/MP4Box; current on master when adjudicated, 2026-07, and no longer so — see Upstream status)* MP4Box IA-sample durations `1`/`959` violate §6.2.2's duration model **and contradict the file's own elst**; FFmpeg (conformant edit-list handling) discards TU0 whole → 648 samples of content lost | ✅ Phase 3c | **S-408** | Executed matrix (doc 60 §2): as-written → FFmpeg −648 / iamfdec ✓ / S-408; stts patched to the §6.2.2 model → **both decoders exact**, S-408 silent; edts removed → FFmpeg exact, S-407 FAIL. FFmpeg demuxer exonerated at source level (`mov_fix_index` whole-frame discard is generic 14496-12 behaviour). **FILED 2026-07-29 as gpac/gpac#3826** (issue + patch offer, doc 71; duplicate search CLEAR with open-control, docs 63/71). **Closed 2026-08-26 — see Upstream status (as read 2026-10-01).** **Repaired in-product (item 13, doc 84):** every Loom MP4Box remux is followed by a `repair_stts` step — byte-size-preserving rewrite of the timing tables to the §6.2.2 model (doc 60's proven `conform` surgery), no-op on conformant tables, so it self-retires at the removal trigger (gpac fix merged AND released). |

## Upstream status (as read 2026-10-01)

The tables above record each failure mode as it was catalogued. This table adds where each
one stands upstream, read on 2026-10-01 from the upstream trackers, release tags and commits.
It is a dated reading and is not kept live. An upstream fix does not retire a row: tool
versions that pre-date the fix still exhibit the failure, and the checks mapped above are
unchanged. Rows not listed carry no upstream status here.

| F | Upstream | Status as read 2026-10-01 |
|---|---|---|
| **F15** | AOMediaCodec/iamf-tools#68 | Fixed upstream by a merged pull request from this project's author (#79, merged 2026-08-05 as `04bc8c8e`; #68 closed the same day); released in iamf-tools v3.0.0. |
| **F16** | AOMediaCodec/iamf-tools#69 | Fixed upstream by a merged pull request from this project's author (#102, merged 2026-09-11; #69 closed on that merge); released in iamf-tools v3.0.0. F18, filed in the same issue, is not fixed by it. |
| **F17** | AOMediaCodec/iamf-tools#70 | Open; not fixed. Documented upstream by a merged pull request from this project's author (#103, merged 2026-09-10, in iamf-tools v3.0.0), which documents `--adm_importance_threshold` as a metadata-only filter; the render behaviour stands. A further pull request from this project's author (#97) is open, not merged. |
| **F18** | AOMediaCodec/iamf-tools#87 (first filed within #69) | Open; not fixed. #102, which closed #69, does not fix it. Filed on its own as #87 (2026-09-07); a pull request from this project's author (#105, opened 2026-09-21) is open, not merged. |
| **F19** | AOMediaCodec/iamf-tools#71 | Fixed upstream by a merged pull request from this project's author (#81, merged 2026-09-02; #71 closed on that merge); released in iamf-tools v3.0.0. |
| **F20** | AOMediaCodec/iamf-tools#72 | Open; no upstream fix. |
| **F24** | AOMediaCodec/iamf-tools#73 | Fixed upstream by a merged pull request from this project's author (#82, merged 2026-08-28; #73 closed on that merge); released in iamf-tools v3.0.0. |
| **F28** | AOMediaCodec/libiamf#170 | iamfdec crash: fixed and released in libiamf v2.0.0; affected the v1.1.0 release tag only. libiamf v2.0.0 was released 2026-09-21; the fix (`3da4c44`) pre-dates the report. No upstream status is recorded here for the decoder_main half of the row. |
| **F29** | FFmpeg/FFmpeg#23968, #24284 (`code.ffmpeg.org`) | Top-back half: reported; fixed upstream, credited by issue reference — #23968 was closed 2026-08-06; the fix is commit `fc02470c`, following another contributor's pull request (#24024). The fix is on FFmpeg master and not in a release: n8.1.3 still carries `BACK_MASK`. Rear-pair half (`AV_CH_BACK_LEFT`/`AV_CH_BACK_RIGHT` at 1.41 on 7.1-derived layouts): filed separately as #24284 (2026-08-26); open. |
| **F31** | FFmpeg/FFmpeg#24285 (`code.ffmpeg.org`) | Start-trim loss on `-c copy`: reported; fixed upstream, credited by issue reference; released in FFmpeg n8.1.3. #24285 was opened 2026-08-26 and closed 2026-09-07; the fix is a maintainer's pull request (#24286), merged 2026-08-28 as `3acec0a1`. n8.1.3 carries it as backport `1005b294ff`, so `git tag --contains 3acec0a1` does not list that tag. |
| **F32** | gpac/gpac#3826 | Fixed on gpac master (`bc1fb9d8fc`); attribution open — the commit references no issue, and no credit is claimed here. Not in a release: `v26.07.0`, the latest gpac release, does not contain it. #3826 was closed 2026-08-26 by its reporter. Loom's `repair_stts` step stays until a gpac release carries the fix. |

*Credited by issue reference* means that the fixing commit's message cites the issue, and no
more than that: neither FFmpeg fix carries a `Reported-by:` trailer.

## Coverage summary (post-Phase 2)

- **Covered Phase 1 (descriptor):** F1, F2, F4-structural, F7-declared, F12, F23, F24 (+partial F3, F9, F21).
- **Covered Phase 2 (L3 rendered):** F4-essence (beds), F7-measured, F9-full, F19/F20 signatures, F21-full, F27, F28 (via extraction), F29 (calibrated).
- **Needs the source master:** ~~F17, F18~~ (**closed Phase 3** — `sentinel adm-compare`, S-330/S-331/S-332, still source-referenced by nature), exact F19/F20 position verification, SN3D-vs-N3D (F3 half) — the position/normalization half remains transpiler QC (doc 13).
- **Out of scope for a content validator (by design, PRD Non-Goals):** F5, F6, F8, F10, F11, F13, F22, F26 (tool/build/runtime), and F14–F16 (encoder crashes on ADM **input**, which a pre-flight ADM validator or the packager owns).

## Core conformance checks not tied to a single F-mode

`S-101` sequence-header presence/order · `S-102` profile recognised ·
`S-103` codec-config validity · `S-104/S-105` element/mix presence ·
`S-106` referential integrity · `S-107` OBU ordering · `S-108` clean parse ·
`S-109` profile constraints · `S-210` object element configuration ·
`S-211` position definition presence · `S-212` position definition matches object count ·
`S-213` default position within range · `S-214` element gain offset ·
`S-215` binaural filter profile defined · `S-216` Mix Presentation not ignored by parsers ·
`S-217` object substream channel count (LPCM) ·
`S-401` IAMF brand · `S-402` fast-start · `S-404` IAMF sample entry.

Three of these do more than their one-line names say:

- **`S-102` profile recognised.** `primary_profile` and `additional_profile` are read against the
  six defined profiles (0–5: Simple, Base, Base-Enhanced, Base-Advanced, Advanced-1, Advanced-2);
  6–255 are reserved. A reserved `primary_profile` is a FAIL: a parser is told to discard such
  a sequence. A reserved `additional_profile` is INFO only: the specification does not forbid it.
- **`S-108` clean parse.** Every genuine parse error is reported, whatever its kind: a truncated
  or oversized OBU; a field that cannot be read inside an OBU; a reserved header bit set where
  IAMF v2.0.0 requires 0; a Mix Presentation optional-fields envelope too short to hold its
  fields; an ObjectsConfig, or the extension bytes of a `rendering_config`, that cannot be
  read in a sequence that declares profile 3, 4 or 5;
  and, in MP4, a parse problem met while walking the samples, or sample tables that cannot be
  followed (a fragmented file's samples are not walked). What is passed over for forward
  compatibility — an unknown OBU type, a config that is not modelled — is a note, not a finding.
- **`S-109` profile constraints.** The limits of the declared profiles, computed from the stream
  for each of the six profiles. Per Mix Presentation: the number of audio elements, the channels
  before mixing and the number of sub-mixes the profile admits; for Base, how many of its elements
  may be scalable or scene-based; for the profiles defined before v2.0.0 (Simple, Base,
  Base-Enhanced), no object-based elements. Per sequence: the number of unique Codec Config OBUs,
  the channel total across Audio Elements where the additional profile sets one, and
  Base-Advanced's rule for its first Mix Presentation. What a profile obliges of a bitstream is
  narrow — at least one Mix Presentation has to fit `primary_profile` — so there are three
  outcomes: FAIL when no Mix Presentation fits `primary_profile` or a sequence-wide requirement is
  broken; WARN when one Mix Presentation fits neither declared profile while another fits; INFO
  when the answer turns on a point the specification leaves open. A count that cannot be read is
  never guessed: it adds nothing to a total, and a limit is reported as exceeded only when the
  counts that can be read exceed it on their own. The limit values, their specification citations
  and the points deliberately left unjudged are in `sentinel/checks/l1_profile.py`. A platform
  pack's own profile requirement is reported under `S-109` as well.

**IAMF v2.0.0 content.** What the validator reads and checks:

- **Header semantics.** OBU header bit 6 is read by OBU type, as IAMF v2.0.0 defines it: the
  trimming flag on audio frames, the optional-fields flag on a Mix Presentation, the
  not-a-key-frame flag on a Temporal Delimiter, reserved on every other type. Set on a Sequence
  Header, Codec Config, Audio Element or Parameter Block OBU, it is an `S-108` finding.
- **Mix Presentation optional fields.** When the flag is set, the tags are walked and the
  optional-fields envelope and its two preferred-renderer bytes are read; an envelope too short
  to hold them is an `S-108` finding. The values are recorded, not judged.
- **The six profiles and their limits** — `S-102` and `S-109`, as above.
- **Object-based elements.** `ObjectsConfig` is read from each object-based element inside its
  own size field. `num_objects` is counted, one channel per object, toward the profile limits,
  and judged by `S-210`: 0 is a FAIL; a count above 2 is a WARN, because the specification
  gives a meaning to 1 and 2 only. `S-210` also fails an object-based element whose Audio
  Element OBU has `num_parameters` other than 0, and warns when the element declares more than
  one audio substream. An ObjectsConfig that cannot be read, in a sequence that declares
  profile 3, 4 or 5, is an `S-108` finding. `S-217` checks that a one-object element's
  substream is coded mono and a two-object element's stereo — for LPCM only, where the size of
  a frame gives its channel count (FAIL); it runs on raw IAMF and on MP4-carried frames alike,
  and not on a fragmented MP4, whose samples are not walked.
- **Rendering settings.** For every element of every sub-mix, the `rendering_config` is read in
  full: `headphones_rendering_mode`, `element_gain_offset_flag` and `binaural_filter_profile`
  from its first byte and, inside the extension size field, `num_parameters`, the six
  position parameter definitions (polar, 8-bit and 16-bit Cartesian, each for one object or
  two) with their default positions, and the element gain offset (a value or a range). Bytes
  after those are reserved and skipped. A `rendering_config` with an empty extension — the
  v1.1.0 form — reads exactly as before. Extension bytes that are not this syntax are an
  `S-108` finding in a sequence that declares profile 3, 4 or 5, and a note otherwise (before
  v2.0.0 those bytes were reserved). The checks:
  - `S-211` — an object-based element's `rendering_config` carries a position definition and a
    channel-based or scene-based element's carries none; no `rendering_config` carries a
    mix-gain, demixing, recon-gain or momentary-loudness definition (FAIL). More than one
    position definition for one element is a WARN: the specification asks for one and does not
    say "exactly".
  - `S-212` — the position definition is a single-object one for `num_objects` = 1 and a
    dual-object one for `num_objects` = 2 (FAIL).
  - `S-213` — a default azimuth outside −180..180° or a default elevation outside −90..90°,
    which a parser clips; a default Cartesian coordinate at the one code (−128, −32768) that
    normalises to below −1.0 (WARN).
  - `S-214` — a reserved `element_gain_offset_type`; in a range, a positive lower bound or a
    negative upper bound, which a parser regards as 0 dB (WARN).
  - `S-215` — the reserved `binaural_filter_profile` value 3 (WARN).
  - `S-216` — a Mix Presentation that parsers are told to ignore: a `rendering_config` with the
    reserved `headphones_rendering_mode` 3, or with a parameter definition type that IAMF
    v2.0.0 does not define (WARN). The unknown type is skipped by its size and reported; it is
    not passed over silently.

  The parsed values are shown in the text, HTML and JSON reports and compared by `sentinel diff`.

  Three things are deliberately not judged: an element of a reserved `audio_element_type`
  (3–7), which parsers are told to ignore — it is kept and noted, and its substreams still
  count; a type-2 element whose bytes are not an ObjectsConfig; and a `rendering_config` whose
  extension bytes are not the v2.0.0 syntax.

What it does **not** yet validate: positions over time — a position definition names a
parameter substream, and the Parameter Block OBUs that carry it are not read, so only the
default position is checked; parameter-block payloads of any kind, and the `parameter_id`s that
tie them to their definitions; whether an object's audio substream is coded mono or stereo as
its `num_objects` requires when the codec is Opus, AAC-LC or FLAC (coded frames are not
decoded; `S-217` covers LPCM only); whether a Mix Presentation that `S-216` reports still
counts toward the profile rules of `S-109`; the Metadata OBU. What is not read is passed over
inside the size fields that carry it, without a finding, so a clean report says nothing about
it. The Pro rendered checks (`S-31x`/`S-32x`) are not yet calibrated for v2.0.0 content.
Anything IAMF v2.0.0 adds that is not in the list above is not validated.

## Pro checks: source-referenced (S-33x) and intent-referenced (S-34x)

Both families ship in `iamf-sentinel-pro` and need something *beside* the file under test.
They are collected here because the traceability above is organised by **failure mode**, and
only one of the two families has failure modes to be traced to.

**Source-referenced fidelity QC** — `sentinel adm-compare`; needs the source BW64/ADM
master. F-anchored, so it appears in the rows above rather than here: `S-330` (F16, F18) ·
`S-331` (F17) · `S-332` (F21).

**Intent-conformance QC** — `sentinel intent-compare`; needs the authoring session's
**intent sidecar** beside the delivered ADM BW64. **No F-anchor, by construction.** The
catalogue above is a catalogue of *encoder* failures, found by pushing ADM masters through
IAMF encoders. These checks answer a different question — *does the delivered file render
the way the session said it would?* — and their failure classes come from the corpus ×
authoring-tool cross-validation study, not from the encoder catalogue. What they cover is
the file that is structurally valid, loudness-conformant, and still not what was authored:
the dropped object, the frozen position, the lost gain move.

| Check | Level | Catches |
|---|---|---|
| **S-340** | FAIL | *Intent: bed roster realized* — a bed channel the roster predicts is absent, or the file carries bed channels the session never predicted (chna/pack walk; no audio measurement). |
| **S-341** | FAIL | *Intent: predicted object present and audible* — a predicted, expected-active object has no essence track, or its track is silent: the dropped/muted-object class. |
| **S-342** | FAIL | *Intent: authored trajectory realized* — delivered blocks diverge from the authored trajectory beyond `posDeg` (great-circle, per-slice, p95): the zeroed/frozen-position class. |
| **S-343** | FAIL | *Intent: rendered dominant speaker as predicted* — per-object isolation render; per-slice dominant speaker disagrees with the decode prediction below the `dominantFrac` threshold (clear-dominance slices only). |
| **S-344** | FAIL | *Intent: stem levels and gain automation realized* — a measured stem/channel level (RMS dBFS or BS.1770-4 gated LKFS, conformant weights) or the delivered gain trajectory deviates beyond `levelLu`: the dropped-gain class. |
| **S-345** | FAIL | *Intent: no energy at predicted-silent channels* — the isolation render puts significant energy where the coverage prediction says silence: the wrong-fold class. |
| **S-346** | FAIL | *Intent: sidecar and file describe the same program* — sample rate, duration, bed layout or scene order contradict the sidecar: the wrong-file guard. **When it fires, the dependent intent checks are skipped.** |

The roster, trajectory and level legs need no EAR. The isolation legs (`S-343`, `S-345`) do,
and the tool **refuses rather than silently comparing less** when EAR is absent.
