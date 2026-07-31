"""Parsed IAMF descriptor model (dataclasses).

Plain data holders produced by parser.py and consumed by the checks. Kept
free of validation logic so the parser stays a faithful transcription of the
bitstream and the checks own all judgment (single source of truth per check).

Transcription doctrine: fields the parser can read cheaply are retained even
before any check consumes them (e.g. redundant_copy, output_gain,
opus_mapping_family) — a validator's model should expose what the bitstream
said, and future checks read from here rather than re-parsing.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# -- OBU type numeric assignments (IAMF v1.1.0) ----------------------------
OBU_CODEC_CONFIG = 0
OBU_AUDIO_ELEMENT = 1
OBU_MIX_PRESENTATION = 2
OBU_PARAMETER_BLOCK = 3
OBU_TEMPORAL_DELIMITER = 4
OBU_AUDIO_FRAME = 5           # explicit substream id
OBU_AUDIO_FRAME_ID0 = 6      # 6..23 -> implicit substream id = type-6 (0..17)
OBU_AUDIO_FRAME_ID17 = 23
OBU_SEQUENCE_HEADER = 31

OBU_TYPE_NAME = {
    0: "CodecConfig", 1: "AudioElement", 2: "MixPresentation",
    3: "ParameterBlock", 4: "TemporalDelimiter", 5: "AudioFrame",
    31: "SequenceHeader",
}
for _i in range(6, 24):
    OBU_TYPE_NAME[_i] = f"AudioFrame_ID{_i - 6}"

AUDIO_ELEMENT_CHANNEL = 0
AUDIO_ELEMENT_SCENE = 1
AUDIO_ELEMENT_OBJECT = 2

PROFILE_NAME = {0: "Simple", 1: "Base", 2: "Base-Enhanced"}

# param_definition_type (IAMF v1.1.0 §3.6.1: 0=MIX_GAIN, 1=DEMIXING, 2=RECON_GAIN).
# NOTE: Phase 1 shipped these off by one (demixing=0/recon=1); no Phase-1
# sample or fixture carried an element-level demixing param, so parse and
# mutation results were self-consistent. The first real FFmpeg 7.1.4 encode
# (which writes a demixing param) exposed the skew — found and fixed in
# Phase 2, covered by test_l3_f4_essence_misroute_detected.
PARAM_MIX_GAIN = 0
PARAM_DEMIXING = 1
PARAM_RECON_GAIN = 2


@dataclass
class OBUHeader:
    obu_type: int
    redundant_copy: bool
    trimming_status_flag: bool
    extension_flag: bool
    obu_size: int
    num_samples_to_trim_at_end: int = 0
    num_samples_to_trim_at_start: int = 0
    file_offset: int = 0          # absolute offset of the header's first byte
    payload_offset: int = 0       # absolute offset where the payload begins
    payload_len: int = 0          # bytes of payload (after any trimming/ext fields)


@dataclass
class SequenceHeader:
    ia_code: str
    primary_profile: int
    additional_profile: int
    header: OBUHeader | None = None


@dataclass
class CodecConfig:
    codec_config_id: int
    codec_id: str
    num_samples_per_frame: int
    audio_roll_distance: int
    # decoder-config extras (best effort per codec)
    bit_depth: int | None = None
    sample_rate: int | None = None
    opus_pre_skip: int | None = None
    opus_mapping_family: int | None = None
    header: OBUHeader | None = None


@dataclass
class ChannelLayerConfig:
    loudspeaker_layout: int
    output_gain_is_present: bool
    recon_gain_is_present: bool
    substream_count: int
    coupled_substream_count: int
    expanded_loudspeaker_layout: int | None = None
    output_gain_flags: int | None = None
    output_gain: int | None = None


@dataclass
class AmbisonicsConfig:
    mode: int                         # 0 mono, 1 projection
    output_channel_count: int
    substream_count: int
    coupled_substream_count: int = 0
    channel_mapping: list[int] = field(default_factory=list)
    order: int | None = None          # derived from output_channel_count


@dataclass
class ParamDefinition:
    param_definition_type: int | None   # None for mix-gain (context-known)
    parameter_id: int
    parameter_rate: int
    param_definition_mode: int
    duration: int | None = None
    constant_subblock_duration: int | None = None
    default_mix_gain: int | None = None
    rate_present: bool = True          # False signals the F1 "rate missing" class


@dataclass
class AudioElement:
    audio_element_id: int
    audio_element_type: int
    codec_config_id: int
    num_substreams: int
    audio_substream_ids: list[int]
    parameters: list[ParamDefinition]
    channel_layers: list[ChannelLayerConfig] = field(default_factory=list)
    ambisonics: AmbisonicsConfig | None = None
    header: OBUHeader | None = None


@dataclass
class LoudnessLayout:
    layout_type: int
    sound_system: int | None
    label: str
    info_type: int
    integrated_loudness: float | None = None   # dB (Q7.8 decoded)
    digital_peak: float | None = None
    true_peak: float | None = None
    integrated_raw: int | None = None
    digital_peak_raw: int | None = None


@dataclass
class SubMix:
    audio_element_ids: list[int]
    num_layouts: int
    layouts: list[LoudnessLayout] = field(default_factory=list)


@dataclass
class MixPresentation:
    mix_presentation_id: int
    count_label: int
    language_labels: list[str]
    annotations: list[str]
    sub_mixes: list[SubMix]
    header: OBUHeader | None = None
    friendly_annotations_present: bool = True


@dataclass
class AudioFrameRef:
    substream_id: int
    obu_type: int
    file_offset: int
    payload_len: int
    first_temporal: bool = False
    # Trimming fields retained from the OBU header (F31: FFmpeg's copy path
    # zeroes these silently — a validator that drops them cannot notice).
    trim_start: int = 0            # num_samples_to_trim_at_start
    trim_end: int = 0              # num_samples_to_trim_at_end


@dataclass
class IAMFModel:
    sequence_header: SequenceHeader | None = None
    codec_configs: dict[int, CodecConfig] = field(default_factory=dict)
    audio_elements: dict[int, AudioElement] = field(default_factory=dict)
    mix_presentations: list[MixPresentation] = field(default_factory=list)
    obu_order: list[str] = field(default_factory=list)   # OBU type names, in file order
    audio_frames: list[AudioFrameRef] = field(default_factory=list)
    parameter_block_ids: list[int] = field(default_factory=list)
    # descriptor byte span (for container/size reporting)
    descriptor_bytes: int = 0
    source: str = ""
    container: str = "raw"          # "raw" | "mp4"
    # non-fatal parse notes captured while reading (surfaced as INFO/L1)
    parse_notes: list[str] = field(default_factory=list)
