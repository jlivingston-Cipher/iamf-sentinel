# Failure-mode → Sentinel check traceability (F1–F34)

The WP1/WP3 failure catalogue is Sentinel's requirements seed and acceptance
test (PRD Goal 1: "the catalogue is the acceptance test"). Every entry is
classified below as: **file-detectable** (a check fires — ✅ Phase 1
descriptor-level, ✅ **Phase 2** L3 rendered), or **out of scope for a content
validator** (a build-environment, encode-time, or runtime issue that is not a
property of a produced IAMF file — several of these belong to the packager
"Loom" or a pre-flight ADM validator, not to Sentinel).

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
| **F28** | Neither reference decoder decodes the A/V MP4 deliverable (decoder_main raw-only; iamfdec `-i1` SIGSEGV on video hdlr) | ✅ Phase 2 (worked around) | — | Sentinel extracts the raw IAMF stream clean-room from the sample tables and oracles that. Disclosure-grade (iamfdec crash). |
| **F29** | *(re-adjudicated docs 64/65 — FFmpeg defect, not a convention split)* ffmpeg `ebur128`'s BACK_MASK weights rears **and top-backs** 1.41 where BS.1770-4 Tables 4/5 say 1.00 (+1.5 LU per over-weighted channel, ≈+0.6 LU aggregate on equal-level 7.1.4 — doc 66 §4); iamf-tools is Table-conformant 12/12 | ✅ Phase 2, tables corrected by **F33** (doc 69) | S-310 | Sentinel measures with the BS.1770-4 tables directly (matching the declared-value producer by construction); `FFMPEG_WEIGHTS` kept solely to model ffmpeg's behaviour for cross-checks. QC-ing IAMF with ffmpeg at tight tolerance flags correct files. **FILED 2026-07-31 as FFmpeg/FFmpeg#23968** (`code.ffmpeg.org` tracker issue, doc 94; currency re-verified on master `5f832b7`, duplicate re-search CLEAR on both trackers with positive controls, docs 66/94) — awaiting maintainer response; patch offered for either scope (minimal: drop `AV_CH_TOP_BACK_*` from `BACK_MASK`; full: key weights on BS.1770 Table 5 positions). |
| **F33** | *(internal, found doc 66 §5, fixed doc 69)* Sentinel's own primary 7.1/7.1.2/7.1.4 tables carried rears (M±135) at 1.41 — the F29 defect class in our own tree, fossilized behind a comment citing a premise doc 64 refuted | ✅ **FIXED** (doc 69): dsp.py + C++ kernel, differential 15/15, regression pin `test_channel_weights_bs1770_conformance` | S-310 (feeds) | Round-trip pin moved −8.688 → −8.974 (weighted path only; unweighted −9.12 unmoved). Heights were always correct; 5.1-family tables were always conformant. **Cross-ecosystem (2026-08-04): also found + fixed independently in Inseglet 1.5.1 (the same author's REAPER MCP extension) — its bed table carried the same M±135 over-weight AND a second boundary cell this fix did not surface: wides Lw/Rw (M±060, 9.1.6, boundary-inclusive) at 1.00 where Table 5 says 1.41. Its `unit.bed_weights` pin mirrors sentinel-pro's conformance vectors as a hard-coded second witness. |
| **F34** | *(internal, found doc 69 §4 — unmasked by the F33 fix, defect pre-existing)* Loom's ffmpeg one-shot backend injected **ebur128-measured** declared loudness; on 7.1.x layouts those values carried F29's over-weighting (measured −0.554 LU on the parity content) — the emitted file was non-conformant and S-310 correctly FAILed it under the Loom gate | ✅ **FIXED** (doc 70): every Loom `measure_bs1770` step reroutes to the `sentinel-dsp` kernel (one argv, one JSON, all three figures); xfails removed, Loom 235/0; post-fix measured-vs-declared ≤0.005 LU on both oracles | S-310 (detects) | Invisible pre-F33 because Sentinel's own error partially cancelled ffmpeg's (top-backs-only residual ≈0.29 LU < ±0.5). Covers inject AND normalize AND preview paths by construction (the measure step is the reroute point). iamf-tools backend was never affected. `loom 0.8.0`. |

## New Phase-3c entries (trim carriage — docs 57/58, executed this cycle)

| F | Symptom (short) | Sentinel status | Check(s) | Notes |
|---|---|---|---|---|
| **F31** | FFmpeg's IAMF `-c copy` silently strips `num_samples_to_trim_at_start` from the Audio Frame OBUs and writes `elst media_time=0` — value irrecoverable, no warning at any log level (release pin **and** master) | ✅ Phase 3c | **S-407, S-408, S-409** | S-407: OBU trim present but edts/elst missing or `media_time` ≠ Σ start-trim (IAMF v1.1.0 §6.2.2 **SHALL**). S-408: Σstts ≠ TUs×nspf − end-trim (§6.2.2 duration model). S-409: Opus `pre_skip` > 0 with no trim fields anywhere — the remux fingerprint, raw or MP4. Executed on the doc-57 evidence files: `ffmpeg-remux.mp4` → S-408+S-409; raw `-c copy` → S-409; the encode path stays clean (ADR-1 unaffected). |
| **F32** | *(adjudicated doc 60 — GPAC/MP4Box, current on master)* MP4Box IA-sample durations `1`/`959` violate §6.2.2's duration model **and contradict the file's own elst**; FFmpeg (conformant edit-list handling) discards TU0 whole → 648 samples of content lost | ✅ Phase 3c | **S-408** | Executed matrix (doc 60 §2): as-written → FFmpeg −648 / iamfdec ✓ / S-408; stts patched to the §6.2.2 model → **both decoders exact**, S-408 silent; edts removed → FFmpeg exact, S-407 FAIL. FFmpeg demuxer exonerated at source level (`mov_fix_index` whole-frame discard is generic 14496-12 behaviour). **FILED 2026-07-29 as gpac/gpac#3826** (issue + patch offer, doc 71; duplicate search CLEAR with open-control, docs 63/71) — awaiting maintainer response; PR ready on agreement. **Repaired in-product (item 13, doc 84):** every Loom MP4Box remux is followed by a `repair_stts` step — byte-size-preserving rewrite of the timing tables to the §6.2.2 model (doc 60's proven `conform` surgery), no-op on conformant tables, so it self-retires at the removal trigger (gpac fix merged AND released). |

## Coverage summary (post-Phase 2)

- **Covered Phase 1 (descriptor):** F1, F2, F4-structural, F7-declared, F12, F23, F24 (+partial F3, F9, F21).
- **Covered Phase 2 (L3 rendered):** F4-essence (beds), F7-measured, F9-full, F19/F20 signatures, F21-full, F27, F28 (via extraction), F29 (calibrated).
- **Needs the source master:** ~~F17, F18~~ (**closed Phase 3** — `sentinel adm-compare`, S-330/S-331/S-332, still source-referenced by nature), exact F19/F20 position verification, SN3D-vs-N3D (F3 half) — the position/normalization half remains transpiler QC (doc 13).
- **Out of scope for a content validator (by design, PRD Non-Goals):** F5, F6, F8, F10, F11, F13, F22, F26 (tool/build/runtime), and F14–F16 (encoder crashes on ADM **input**, which a pre-flight ADM validator or the packager owns).

## Core conformance checks not tied to a single F-mode

`S-101` sequence-header presence/order · `S-102` profile recognised ·
`S-103` codec-config validity · `S-104/S-105` element/mix presence ·
`S-106` referential integrity · `S-107` OBU ordering · `S-108` clean parse
(truncation) · `S-109` profile constraints · `S-401` IAMF brand ·
`S-402` fast-start · `S-404` IAMF sample entry.
