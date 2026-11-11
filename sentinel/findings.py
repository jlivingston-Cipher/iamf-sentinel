"""Findings model and the stable Sentinel check registry (PRD R6).

Check-ID taxonomy is a stable public contract (tool vendors cite
"passes S-1xx…S-4xx at vX.Y" in self-certification):

    S-1xx  structural / L1        (OBU syntax, ordering, referential integrity)
    S-2xx  channel-semantics / L2 (substream topology — the F4 killer;
                                   S-21x object and rendering configuration)
    S-3xx  loudness (descriptor)  (declared-loudness sanity; measured render = Phase 2)
    S-4xx  container / profile     (MP4 brands, fast-start, RFC6381)

Severity: FAIL (conformance violation) / WARN (risk or non-canonical) /
INFO (observation). Profiles may override a check's severity.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    FAIL = 2

    @property
    def label(self) -> str:
        return {0: "INFO", 1: "WARN", 2: "FAIL"}[int(self)]


@dataclass(frozen=True)
class CheckSpec:
    id: str
    title: str
    layer: str                 # "L1" | "L2" | "L3" | "container"
    default_severity: Severity
    f_refs: tuple[str, ...] = ()   # WP1/WP3 failure-mode IDs this check catches
    description: str = ""


@dataclass
class Finding:
    check_id: str
    severity: Severity
    message: str
    where: str = ""            # e.g. "audio_element 300" / "mix_presentation 42 / Stereo"
    expected: str | None = None
    found: str | None = None
    f_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = {
            "check_id": self.check_id,
            "severity": self.severity.label,
            "message": self.message,
        }
        if self.where:
            d["where"] = self.where
        if self.expected is not None:
            d["expected"] = self.expected
        if self.found is not None:
            d["found"] = self.found
        if self.f_refs:
            d["failure_modes"] = list(self.f_refs)
        return d


# -- The registry ----------------------------------------------------------
REGISTRY: dict[str, CheckSpec] = {}


def _reg(spec: CheckSpec) -> CheckSpec:
    REGISTRY[spec.id] = spec
    return spec


S = Severity
# L1 structural
_reg(CheckSpec("S-101", "IA Sequence Header present and first", "L1", S.FAIL,
               description="ia_sequence_header must be the first OBU with ia_code 'iamf'."))
_reg(CheckSpec("S-102", "Profile recognised", "L1", S.FAIL,
               description="primary/additional profile is one of the six defined profiles "
               "(0-5: Simple, Base, Base-Enhanced, Base-Advanced, Advanced-1, Advanced-2); "
               "6-255 are reserved. A reserved primary_profile fails (parsers are told "
               "to discard such a sequence); a reserved additional_profile is always "
               "INFO (the text does not forbid it)."))
_reg(CheckSpec("S-103", "Codec config valid", "L1", S.FAIL,
               description="codec_id known; num_samples_per_frame>0; audio_roll_distance<=0."))
_reg(CheckSpec("S-104", "Audio element present", "L1", S.FAIL))
_reg(CheckSpec("S-105", "Mix presentation present", "L1", S.FAIL,
               description="At least one mix presentation (IAMF requires >=1)."))
_reg(CheckSpec("S-106", "Referential integrity", "L1", S.FAIL, ("F4",),
               "Every codec_config_id / audio_element_id reference resolves."))
_reg(CheckSpec("S-107", "OBU ordering", "L1", S.FAIL,
               description="Descriptor OBUs precede audio frames; configs precede referents."))
_reg(CheckSpec("S-108", "Clean parse (no truncation)", "L1", S.FAIL,
               description="Stream parses fully with no truncated/oversized OBU."))
_reg(CheckSpec("S-109", "Profile constraints", "L1", S.WARN,
               description="Element/channel counts within the declared profile's limits."))

# L2 channel-semantics (F4 killer)
_reg(CheckSpec("S-201", "Substream topology vs declared layout", "L2", S.FAIL, ("F4",),
               "Declared substream_count/coupled_substream_count match the loudspeaker_layout "
               "(coupled pairs first, C/LFE last), layer by layer: the whole layout for the "
               "first layer, what its layout adds to the layer below for each layer above "
               "it. The F4 silent-corruption detector."))
_reg(CheckSpec("S-202", "Substream count consistency", "L2", S.FAIL, ("F4",),
               "num_substreams equals the layer topology; coupled<=substream; mono has no coupled."))
_reg(CheckSpec("S-203", "Ambisonics completeness", "L2", S.FAIL, ("F2", "F3"),
               "output_channel_count=(N+1)^2; substream_count matches; ACN mapping is a full "
               "permutation with no gaps/duplicates."))
_reg(CheckSpec("S-204", "Parameter rate sanity", "L2", S.FAIL, ("F1",),
               "Every param_definition has a non-zero parameter_rate."))
_reg(CheckSpec("S-205", "Substream id uniqueness", "L2", S.FAIL, ("F4",),
               "audio_substream_ids unique across elements."))
_reg(CheckSpec("S-206", "Temporal-unit timing", "L2", S.WARN, ("F9",),
               "First temporal unit not duplicated; frame timing plausible."))
_reg(CheckSpec("S-207", "Frame/substream coverage", "L2", S.FAIL, ("F4",),
               "Every declared substream carries frames; no frame references an undeclared "
               "substream (dropped/duplicated substream detection)."))
_reg(CheckSpec("S-208", "Annotation presence", "L2", S.WARN, ("F24",),
               "Mix-presentation/element annotations are not dropped or template placeholders."))

# L2 object and rendering semantics (IAMF v2.0.0: object-based elements, and
# the RenderingConfig a Mix Presentation gives each element). Descriptors,
# plus LPCM frame sizes for S-217; positions over time (Parameter Block OBUs)
# are read into the model (IA-0051 stage 1) and not yet judged.
_reg(CheckSpec("S-210", "Object element configuration", "L2", S.FAIL,
               description="An object-based element's num_objects is not 0 and its Audio "
               "Element OBU has num_parameters = 0 (FAIL). num_objects above 2, and "
               "more than one audio substream, have no meaning the specification "
               "gives them (WARN)."))
_reg(CheckSpec("S-211", "Position definition presence", "L2", S.FAIL,
               description="The rendering_config of an object-based element carries a "
               "position definition (param_definition_type 3-8); that of a channel-based "
               "or scene-based element carries none; no rendering_config carries a "
               "mix-gain, demixing, recon-gain or momentary-loudness definition (FAIL). "
               "More than one position definition for one element is a WARN."))
_reg(CheckSpec("S-212", "Position definition matches object count", "L2", S.FAIL,
               description="A one-object element uses POLAR, CART8 or CART16; a two-object "
               "element uses DUAL_POLAR, DUAL_CART8 or DUAL_CART16."))
_reg(CheckSpec("S-213", "Default position within range", "L2", S.WARN,
               description="A position definition's default azimuth is within -180..180 "
               "degrees and its default elevation within -90..90 (parsers clip values "
               "outside); a default Cartesian coordinate is not the one code that "
               "normalises to below -1.0."))
_reg(CheckSpec("S-214", "Element gain offset", "L2", S.WARN,
               description="element_gain_offset_type is VALUE or RANGE (2-255 are "
               "reserved); in a RANGE the lower bound is not positive and the upper "
               "bound is not negative (parsers regard either as 0 dB)."))
_reg(CheckSpec("S-215", "Binaural filter profile defined", "L2", S.WARN,
               description="binaural_filter_profile is AMBIENT, DIRECT or REVERBERANT; "
               "3 is reserved."))
_reg(CheckSpec("S-216", "Mix Presentation not ignored by parsers", "L2", S.WARN,
               description="No rendering_config makes parsers ignore its Mix "
               "Presentation: headphones_rendering_mode is not the reserved value 3, "
               "and every param_definition_type is one IAMF v2.0.0 defines."))
_reg(CheckSpec("S-217", "Object substream channel count (LPCM)", "L2", S.FAIL,
               description="The audio substream of a one-object element is coded mono "
               "and that of a two-object element stereo. Read from frame sizes, so "
               "judged for LPCM only: an LPCM frame is num_samples_per_frame samples "
               "of one or two channels at sample_size bits. Frames of other codecs "
               "are not decoded and not judged."))

# L3 loudness (descriptor-derived; measured render is Phase 2)
_reg(CheckSpec("S-301", "Loudness not unmeasured-default", "L3", S.FAIL, ("F7",),
               "No layout carries integrated=0.0 AND digital_peak=0.0 (the FFmpeg 0.0 default)."))
_reg(CheckSpec("S-302", "Loudness layout coverage", "L3", S.WARN, ("F23",),
               "Multichannel/scene programs declare loudness for their native layout, not "
               "stereo only (the Dolby-mode stereo-only-loudness gap)."))
_reg(CheckSpec("S-303", "True peak present", "L3", S.INFO,
               description="info_type advertises true peak; absent = not written (informational)."))
_reg(CheckSpec("S-304", "Declared peak headroom", "L3", S.WARN, ("F21",),
               "Declared digital/true peak is below 0 dBFS (clipping hazard)."))

# L3 rendered QC (Phase 2 — decoder oracle + own BS.1770-4; PRD R3)
_reg(CheckSpec("S-310", "Measured loudness matches declared", "L3", S.FAIL, ("F7", "F25"),
               "Per mix presentation x declared layout: decode via reference-decoder oracle, "
               "measure BS.1770-4 integrated loudness, compare to the embedded value within "
               "tolerance (default ±0.5 LU). The measured half of the F7 class."))
_reg(CheckSpec("S-311", "Measured peak matches declared", "L3", S.WARN, ("F7",),
               "Measured digital peak (and true peak when declared) within tolerance of the "
               "embedded values (default ±0.3 dB)."))
_reg(CheckSpec("S-312", "Rendered decode failure", "L3", S.FAIL,
               description="A declared layout fails to decode on every available reference "
               "decoder (decode-failure = hard fail, PRD R3)."))
_reg(CheckSpec("S-313", "Oracle divergence", "L3", S.WARN,
               description="The reference decoders disagree on the same render (loudness "
               "beyond tolerance, or one decodes what the other cannot) — ORACLE_DIVERGENCE, "
               "PRD Open Question 5."))
_reg(CheckSpec("S-314", "Decoded-PCM headroom", "L3", S.WARN, ("F19", "F20", "F21"),
               "Measured true/digital peak of a rendered layout at/above full scale — the "
               "executed F21 clipping class (3OA fold, origin collapse), on real decoded PCM."))
_reg(CheckSpec("S-320", "Channel identity: silent channels", "L3", S.WARN, ("F4",),
               "A rendered channel is silent while the program carries signal — the "
               "missing-channel signature of the F4 essence misroute (WP1: Rtf/Rtb lost)."))
_reg(CheckSpec("S-321", "Channel identity: duplicate channels", "L3", S.WARN, ("F4",),
               "Two rendered channels are effectively the same signal (corr >= 0.999, level "
               "delta <= 0.1 dB) — the duplication signature of the F4 essence misroute "
               "(WP1: C into both side surrounds, LFE into both rears)."))
_reg(CheckSpec("S-322", "Spatial degeneracy (origin-collapse signature)", "L3", S.WARN,
               ("F19", "F20"),
               "Windowed Gerzon energy-vector magnitude near zero across the program with "
               "high inter-channel correlation — everything panned to the origin (spherical-"
               "coordinate zeroing F19, position-less beds F20)."))

# Source-referenced fidelity QC (Phase 3 — needs the source ADM; adm_compare)
_reg(CheckSpec("S-330", "Authored gain trajectory realized", "L3", S.FAIL, ("F16", "F18"),
               "The output's level trajectory diverges steadily from an independent "
               "reference render (EAR) of the source ADM — authored gain automation "
               "was discarded on ingest (WP3: block <gain> never stored, object <gain> "
               "aborts; the only honored path is a constant default)."))
_reg(CheckSpec("S-331", "Importance filtering effective", "L3", S.FAIL, ("F17",),
               "With an importance threshold requested at encode, the output still "
               "matches the unfiltered source better than the importance-filtered "
               "reference — below-threshold objects shipped anyway (WP3: the metadata "
               "filter prunes audioObjects but the splicer pans every input channel)."))
_reg(CheckSpec("S-332", "Source-vs-output level agreement", "L3", S.WARN, ("F21",),
               "Median level divergence between the source reference render and the "
               "produced IAMF beyond tolerance — re-render/fold level shift (headroom "
               "risk class)."))
_reg(CheckSpec("S-333", "ADM conversion: each track's level preserved", "L3", S.FAIL, (),
               "A static bed channel or object of the source ADM arrives in the "
               "produced IAMF at a level other than its block gain x object gain, read "
               "per track from the LPCM the converter wrote (least squares against the "
               "source's own tracks; ACN 0 for a scene element). Calibrated to BS.2127, "
               "which has no distance-to-level term: iamf-tools' importer attenuates by "
               "1/max(|p|, 0.5), so a room-centric 5.1 bed's corners arrive 3.01 dB "
               "down and a panned LFE 4.77 dB down (IA-0057, IA-0076)."))
_reg(CheckSpec("S-334", "ADM conversion: each track's direction preserved", "L3", S.FAIL, (),
               "A static bed channel or object of the source ADM arrives in a scene "
               "element away from its authored direction: the polar position as "
               "authored, a Cartesian one through BS.2127-0 §10.1.2 point_cart_to_polar "
               "(the cube corner (1, 1, 0) is azimuth -30). Read from ACN 1-3 of the "
               "track's contribution; iamf-tools' importer takes atan2 of the cube "
               "coordinates instead (-45) (IA-0057, IA-0076)."))

# Intent-conformance QC (B1 — needs the session's intent sidecar;
# sentinel_pro.intent_compare). The sidecar is the authoring session's own
# prediction of its export; these checks answer "does the file render as the
# session intended?" — the class that is structurally valid, loudness-
# conformant, and wrong. No WP1/WP3 f_refs: the failure classes come from the
# corpus x Inseglet cross-validation study, not the encoder catalogue.
_reg(CheckSpec("S-340", "Intent: bed roster realized", "L3", S.FAIL, (),
               "A bed channel the sidecar's roster predicts is absent from the "
               "delivered file, or the file carries bed channels the session "
               "never predicted (chna/pack walk; no audio measurement)."))
_reg(CheckSpec("S-341", "Intent: predicted object present and audible", "L3",
               S.FAIL, (),
               "An object the sidecar predicts (and expects active) has no "
               "essence track in the delivered file, or its track is silent — "
               "the dropped/muted-object class."))
_reg(CheckSpec("S-342", "Intent: authored trajectory realized", "L3", S.FAIL,
               (),
               "The delivered block trajectory diverges from the sidecar's "
               "authored trajectory beyond posDeg (great-circle, per-slice, "
               "p95) — the zeroed/frozen-position class."))
_reg(CheckSpec("S-343", "Intent: rendered dominant speaker as predicted",
               "L3", S.FAIL, (),
               "Per-object isolation render (EAR): the per-slice dominant "
               "speaker disagrees with the sidecar's decode prediction below "
               "the dominantFrac agreement threshold (clear-dominance slices "
               "only)."))
_reg(CheckSpec("S-344", "Intent: stem levels and gain automation realized",
               "L3", S.FAIL, (),
               "A measured stem/channel level (RMS dBFS or BS.1770-4 gated "
               "LKFS, conformant weights) or the delivered gain trajectory "
               "deviates from the sidecar's prediction beyond levelLu — the "
               "dropped-gain class."))
_reg(CheckSpec("S-345", "Intent: no energy at predicted-silent channels",
               "L3", S.FAIL, (),
               "The isolation render puts significant energy at a channel the "
               "sidecar's coverage prediction marks silent — the wrong-fold "
               "class."))
_reg(CheckSpec("S-346", "Intent: sidecar and file describe the same program",
               "L3", S.FAIL, (),
               "Sample rate, duration, bed layout, or scene order contradict "
               "the sidecar — the wrong-file guard. When it fires, the "
               "dependent intent checks are skipped."))

# Container / profile
_reg(CheckSpec("S-401", "IAMF brand present", "container", S.FAIL,
               description="MP4 compatible_brands includes 'iamf'."))
_reg(CheckSpec("S-402", "Fast-start (moov before mdat)", "container", S.WARN,
               description="moov precedes mdat for progressive playback / ingest."))
_reg(CheckSpec("S-403", "RFC6381 codec string", "container", S.WARN, ("F12",),
               "codecs string iamf.PPP.AAA.<fourcc> uses the codec 4CC verbatim ('Opus', not 'opus')."))
_reg(CheckSpec("S-404", "IAMF sample entry", "container", S.FAIL,
               description="An 'iamf' sample entry exists in the MP4."))
_reg(CheckSpec("S-405", "MP4 timing sanity (stts/ctts)", "container", S.WARN, ("F9",),
               "Sample durations are positive and monotonic-consistent; the F9 MP4Box "
               "first-TU DTS-patch residue surfaces here (R4 depth, Phase 2)."))
_reg(CheckSpec("S-406", "A/V duration coherence", "container", S.WARN,
               description="Audio and video track durations agree within 250 ms (R4)."))
# Trim carriage (F31: FFmpeg's IAMF copy path silently strips start-trim)
_reg(CheckSpec("S-407", "TRIM_EDIT_LIST_MISSING — start-trim edit list", "container",
               S.FAIL, ("F31",),
               "If audio-frame OBUs carry samples to trim, edts/elst SHALL be present "
               "(IAMF v1.1.0 §6.2.2) and elst media_time must equal the summed "
               "start-trim. Missing or contradicting edit list is a conformance FAIL."))
_reg(CheckSpec("S-408", "TRIM_STTS_MISMATCH — stts vs trim bookkeeping", "container",
               S.WARN, ("F31",),
               "Total stts duration must equal TUs x num_samples_per_frame minus the "
               "OBU end-trim (§6.2.2 duration model: start-trim included, end-trim "
               "excluded). Catches short first-sample durations (MP4Box stts skew) "
               "and end-trim not reflected in the sample table."))
_reg(CheckSpec("S-409", "TRIM_FIELDS_ABSENT — codec delay never trimmed", "container",
               S.WARN, ("F31",),
               "Opus essence with Codec Config pre_skip > 0 but no "
               "num_samples_to_trim_at_start anywhere in the stream — the decoder "
               "delay ships as content. The FFmpeg '-c copy' remux fingerprint; "
               "evaluated on raw IAMF and on MP4-carried frames alike."))


def spec(check_id: str) -> CheckSpec:
    return REGISTRY[check_id]
