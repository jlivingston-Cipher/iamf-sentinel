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

# primary_profile / additional_profile values (IAMF v2.0.0 Sequence Header
# semantics, v2:688-695). 0..2 are also the v1.1.0 set; 6..255 are "Reserved
# for future profiles".
PROFILE_NAME = {0: "Simple", 1: "Base", 2: "Base-Enhanced",
                3: "Base-Advanced", 4: "Advanced-1", 5: "Advanced-2"}


def profile_label(value: int) -> str:
    """Display name of a profile value; a value outside 0..5 is reserved."""
    return PROFILE_NAME.get(value, f"reserved ({value})")

# param_definition_type (IAMF v1.1.0 §3.6.1: 0=MIX_GAIN, 1=DEMIXING, 2=RECON_GAIN).
# NOTE: Phase 1 shipped these off by one (demixing=0/recon=1); no Phase-1
# sample or fixture carried an element-level demixing param, so parse and
# mutation results were self-consistent. The first real FFmpeg 7.1.4 encode
# (which writes a demixing param) exposed the skew — found and fixed in
# Phase 2, covered by test_l3_f4_essence_misroute_detected.
PARAM_MIX_GAIN = 0
PARAM_DEMIXING = 1
PARAM_RECON_GAIN = 2
# IAMF v2.0.0 adds 3..9 (Parameter Definition Types table, v2:2183-2214).
# 3..8 are the position-based definitions of an object-based element; they
# are carried in a Mix Presentation's RenderingConfig(), not in the Audio
# Element OBU.
PARAM_POLAR = 3
PARAM_CART8 = 4
PARAM_CART16 = 5
PARAM_DUAL_POLAR = 6
PARAM_DUAL_CART8 = 7
PARAM_DUAL_CART16 = 8
PARAM_MOMENTARY_LOUDNESS = 9

PARAM_TYPE_NAME = {
    0: "MIX_GAIN", 1: "DEMIXING", 2: "RECON_GAIN", 3: "POLAR", 4: "CART8",
    5: "CART16", 6: "DUAL_POLAR", 7: "DUAL_CART8", 8: "DUAL_CART16",
    9: "MOMENTARY_LOUDNESS",
}

# animation_type of AnimatedParameterData() (Animation Types table,
# v2:2391-2413). v1.1.0 defined 0..2 only (v1.1:1634-1639); 3 and 4 are new
# in v2.0.0. Every other value is undefined.
ANIMATION_STEP = 0
ANIMATION_LINEAR = 1
ANIMATION_BEZIER = 2
ANIMATION_INTER_LINEAR = 3
ANIMATION_INTER_BEZIER = 4
ANIMATION_TYPE_NAME = {0: "STEP", 1: "LINEAR", 2: "BEZIER", 3: "INTER_LINEAR",
                       4: "INTER_BEZIER"}

# Where a parameter definition can be declared (ParamDeclaration.role).
ROLE_DEMIXING = "demixing"                   # Audio Element OBU (v2:784-785)
ROLE_RECON_GAIN = "recon_gain"               # Audio Element OBU (v2:787-788)
ROLE_ELEMENT_MIX_GAIN = "element_mix_gain"   # Mix Presentation sub-mix element (v2:1347)
ROLE_OUTPUT_MIX_GAIN = "output_mix_gain"     # Mix Presentation sub-mix (v2:1349)
ROLE_POSITION = "position"                   # RenderingConfig() (v2:1467-1479)
ROLE_MOMENTARY_LOUDNESS = "momentary_loudness"   # LoudnessInfo() (v2:1999-2000)

# Bits of recon_gain_flags that name a channel (v2:2535-2550): b0..b6 in the
# first leb128 byte, b7..b11 in the second. n(i) "SHALL be 7 or 12".
RECON_GAIN_FLAG_BITS = 12

# Subblocks a parameter block can declare before the reader stops: a
# subblock may be coded in zero bytes (recon gain with no layer flagged), so
# the payload does not bound the count on its own. 2^18 covers one second of
# single-tick subblocks at 192 kHz, the longest block any profile allows
# (v2:3150).
MAX_PARAMETER_SUBBLOCKS = 1 << 18


def implied_num_subblocks(duration: int, constant_subblock_duration: int) -> int:
    """num_subblocks when constant_subblock_duration is not 0:
    ceil(duration / constant_subblock_duration) (v2:2260, v2:2357)."""
    return -(-duration // constant_subblock_duration)


def parameter_block_timing(block: "ParameterBlock",
                           pd: "ParamDefinition | None") -> tuple[int | None, list[int]]:
    """(duration, subblock durations) in ticks that govern a parameter block:
    the block's own fields in param_definition_mode 1, the definition's in
    mode 0 (v2:2248-2252). The last subblock of a constant-duration split
    takes what is left (v2:2261-2262). (None, []) when the fields are not
    there to derive from."""
    if block.param_definition_mode == 1:
        duration, csd = block.duration, block.constant_subblock_duration
        coded = [sb.subblock_duration for sb in block.subblocks]
    elif pd is not None and block.param_definition_mode == 0:
        duration, csd = pd.duration, pd.constant_subblock_duration
        coded = list(pd.subblock_durations)
    else:
        return None, []
    if duration is None or csd is None:
        return duration, []
    if csd != 0:
        n = implied_num_subblocks(duration, csd)
        return duration, ([csd] * (n - 1) + [duration - (n - 1) * csd] if n else [])
    return duration, [d for d in coded if d is not None]

# Objects positioned by each position-based definition. This is also the
# num_objects each one is allowed for (v2:1554-1562).
POSITION_PARAM_OBJECTS = {
    PARAM_POLAR: 1, PARAM_CART8: 1, PARAM_CART16: 1,
    PARAM_DUAL_POLAR: 2, PARAM_DUAL_CART8: 2, PARAM_DUAL_CART16: 2,
}
POLAR_PARAM_TYPES = (PARAM_POLAR, PARAM_DUAL_POLAR)

# RenderingConfig() first byte (v2:1457-1461). In both two-bit fields the
# value 3 is "Reserved for future use" (v2:1515, v2:1537). The specification
# names the binaural filter profiles (v2:1534-1536) and describes the
# headphones rendering modes without naming them (v2:1507-1513).
DEFINED_HEADPHONES_RENDERING_MODES = (0, 1, 2)
BINAURAL_FILTER_PROFILE_NAME = {0: "AMBIENT", 1: "DIRECT", 2: "REVERBERANT"}

# element_gain_offset_type (Element Gain Offset Types table, v2:1612-1628);
# 2..255 are reserved.
GAIN_OFFSET_VALUE = 0
GAIN_OFFSET_RANGE = 1
GAIN_OFFSET_TYPE_NAME = {0: "VALUE", 1: "RANGE"}


@dataclass
class OBUHeader:
    obu_type: int
    redundant_copy: bool
    trimming_status_flag: bool    # header bit 6 on audio-frame OBUs (types 5..23)
    extension_flag: bool
    obu_size: int
    num_samples_to_trim_at_end: int = 0
    num_samples_to_trim_at_start: int = 0
    file_offset: int = 0          # absolute offset of the header's first byte
    payload_offset: int = 0       # absolute offset where the payload begins
    payload_len: int = 0          # bytes of payload (after any trimming/ext fields)
    # Header bit 6 on the other OBU types, as IAMF v2.0.0 OBUHeader() names it
    # (v1.1.0 calls the bit obu_trimming_status_flag for every type and
    # requires 0 outside audio frames). At most one bit-6 field is True.
    optional_fields_flag: bool = False   # Mix Presentation OBU (type 2)
    is_not_key_frame: bool = False       # Temporal Delimiter OBU (type 4)
    reserved_flag: bool = False          # any other type; SHALL be 0


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
    # Channels actually coded: substream_count + coupled_substream_count
    # (derived). Differs from output_channel_count for mixed-order and
    # projection content; the profile limits do not say which of the two a
    # scene-based element counts as, so both are kept.
    coded_channel_count: int = 0


@dataclass
class ObjectsConfig:
    """ObjectsConfig() of an object-based element (IAMF v2.0.0, v2:1305-1322)."""
    objects_config_size: int          # envelope: bytes after the size field
    num_objects: int                  # one channel of audio per object
    extension_bytes: int = 0          # objects_config_extension_bytes skipped


@dataclass
class ParamDefinition:
    """ParamDefinition() and the fields its subclasses add (v2:2221-2236).

    param_definition_type is a key of PARAM_TYPE_NAME: PARAM_MIX_GAIN for the
    MixGainParamDefinition() of a Mix Presentation, whose type is not coded
    (the context names it). duration, constant_subblock_duration,
    num_subblocks and subblock_durations are as coded, present in mode 0
    only; num_subblocks is coded only when constant_subblock_duration is 0
    (implied_num_subblocks() gives it otherwise)."""
    param_definition_type: int | None
    parameter_id: int
    parameter_rate: int
    param_definition_mode: int
    duration: int | None = None
    constant_subblock_duration: int | None = None
    default_mix_gain: int | None = None
    rate_present: bool = True          # False signals the F1 "rate missing" class
    num_subblocks: int | None = None
    subblock_durations: list[int] = field(default_factory=list)
    reserved: int = 0                  # the 7 bits after param_definition_mode
    # DemixingParamDefinition(): DefaultDemixingInfoParameterData() (v2:809-818)
    default_dmixp_mode: int | None = None
    default_w: int | None = None


@dataclass
class ParamDeclaration:
    """One declaration of a parameter_id in the descriptors: the definition
    and where it was made. The registry (IAMFModel.parameter_definitions)
    keeps every declaration of an id, so an id declared twice, identically
    or not, is on record; the first declaration is the one parameter blocks
    are read by."""
    param: ParamDefinition
    role: str                               # a ROLE_* value
    file_offset: int                        # of the declaring OBU
    redundant_copy: bool = False            # the declaring OBU's obu_redundant_copy
    # The Audio Element of a demixing or recon-gain definition, or the one a
    # sub-mix entry (element_mix_gain, position) renders. None for
    # output_mix_gain and momentary_loudness.
    audio_element_id: int | None = None
    mix_presentation_id: int | None = None
    sub_mix_index: int | None = None        # 0-based position in the sub-mix list
    layout_index: int | None = None         # 0-based loudness layout, momentary_loudness only


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
    # None for an object-based element whose config bytes do not parse as an
    # ObjectsConfig (the object count is then unknown, never guessed; the
    # parser decides whether that is a note or a parse error).
    objects: ObjectsConfig | None = None
    header: OBUHeader | None = None
    # num_parameters as coded. `parameters` holds only the demixing and
    # recon-gain definitions; any other type is skipped and counted here.
    num_parameters: int = 0
    # param_definition_type of every skipped definition, in file order. IAMF
    # v2.0.0 allows only DEMIXING and RECON_GAIN here (v2:856-858); 0 and
    # 3..9 have no Audio Element syntax at all, and types above 9 are carried
    # as param_definition_size + bytes (v2:790-793).
    other_param_definition_types: list[int] = field(default_factory=list)


@dataclass
class PositionParamDefinition:
    """A position-based parameter definition of a RenderingConfig()
    (PolarParamDefinition() .. DualCart16ParamDefinition(), v2:1678-1876)."""
    param_definition_type: int        # 3..8, a key of POSITION_PARAM_OBJECTS
    param: ParamDefinition            # the ParamDefinition() fields it extends
    # The default position of each object, as coded, in syntax order: one
    # triple for the single-object types, two for the dual ones. Polar:
    # (azimuth, elevation, distance) in degrees, degrees and 1/127 of the
    # unit-sphere radius. Cartesian: (x, y, z) in 1/127 (8-bit) or 1/32767
    # (16-bit) of the cube's half-edge.
    defaults: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class ElementGainOffsetConfig:
    """ElementGainOffsetConfig() (v2:1593-1605). Gains are Q7.8 as coded."""
    element_gain_offset_type: int                  # 0 VALUE, 1 RANGE, else reserved
    element_gain_offset: int | None = None         # VALUE
    default_element_gain_offset: int | None = None   # RANGE
    min_element_gain_offset: int | None = None       # RANGE
    max_element_gain_offset: int | None = None       # RANGE
    extension_bytes: int = 0          # reserved type: element_gain_offset_bytes skipped


@dataclass
class RenderingConfig:
    """RenderingConfig() of one audio element in one sub-mix (v2:1457-1491).

    The first byte and rendering_config_extension_size are always read. What
    IAMF v2.0.0 places inside the extension envelope follows; num_parameters
    stays None when the envelope is empty (the v1.1.0 form, which v2.0.0
    streams also use when they have nothing to put there).
    """
    headphones_rendering_mode: int                 # 2 bits; 3 is reserved
    element_gain_offset_flag: bool
    binaural_filter_profile: int                   # 2 bits; 3 is reserved
    reserved: int                                  # 3 bits, ignored by parsers
    rendering_config_extension_size: int
    # False when the envelope bytes do not follow the v2.0.0 syntax: nothing
    # below was read (the parser decides whether that is a note or a parse
    # error), and no check judges this rendering config's parameters.
    extension_read: bool = True
    num_parameters: int | None = None
    position_definitions: list[PositionParamDefinition] = field(default_factory=list)
    # param_definition_type of every other definition, in file order; each is
    # carried as param_definition_size + bytes and skipped (v2:1480-1483).
    other_param_definition_types: list[int] = field(default_factory=list)
    element_gain_offset: ElementGainOffsetConfig | None = None
    extension_bytes: int = 0          # rendering_config_extension_bytes skipped


@dataclass
class MomentaryLoudnessInfo:
    """The momentary-loudness part of a LoudnessInfo() (info_type bit 3,
    v2:1999-2010): its parameter definition and the histogram fields."""
    param: ParamDefinition                 # MomentaryLoudnessParamDefinition()
    num_bin_pairs_minus_one: int
    bin_width_minus_one: int
    first_bin_center: int                  # LKFS magnitude; the centre is -1 x this
    reserved: int
    counts: list[int] = field(default_factory=list)   # (num_bin_pairs_minus_one + 1) x 2


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
    # The info_type_size envelope (v2:1996-2018), read as IAMF v2.0.0 lays it
    # out: None when the stream carries none (info_type bits 2..7 clear).
    info_type_size: int | None = None
    momentary_loudness: MomentaryLoudnessInfo | None = None   # bit 3
    loudness_range: int | None = None                         # bit 4, LU
    info_type_bytes: int = 0               # reserved bytes left in the envelope
    # False when the envelope does not hold the syntax its bits announce;
    # nothing of it is kept and the envelope is skipped whole (a note).
    info_type_read: bool = True


@dataclass
class SubMix:
    audio_element_ids: list[int]
    num_layouts: int
    layouts: list[LoudnessLayout] = field(default_factory=list)
    # One per entry of audio_element_ids, in the same order.
    rendering_configs: list[RenderingConfig] = field(default_factory=list)
    # element_mix_gain of each entry, in the same order, and the sub-mix's
    # output_mix_gain (MixGainParamDefinition(), v2:1347-1349).
    element_mix_gains: list[ParamDefinition] = field(default_factory=list)
    output_mix_gain: ParamDefinition | None = None


@dataclass
class MixPresentation:
    mix_presentation_id: int
    count_label: int
    language_labels: list[str]
    annotations: list[str]
    sub_mixes: list[SubMix]
    header: OBUHeader | None = None
    friendly_annotations_present: bool = True
    # Optional fields (IAMF v2.0.0 MixPresentationOBU(), present only when the
    # header's optional_fields_flag is 1); None when the OBU carries none.
    optional_fields_size: int | None = None
    preferred_loudspeaker_renderer: int | None = None   # 0 = NONE, 1..255 reserved
    preferred_binaural_renderer: int | None = None      # 0 = NONE, 1..255 reserved


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
    # Bytes of the coded audio_frame itself: payload_len less the explicit
    # audio_substream_id of an OBU of type 5. The frame is not decoded.
    frame_bytes: int = 0


@dataclass
class AnimatedValue:
    """One AnimatedParameterData<T> instance (v2:2420-2443), values as coded.
    The fields an animation type does not carry stay None: STEP has the
    start only, LINEAR start and end, BEZIER all four, INTER_LINEAR the end
    only, INTER_BEZIER end, control and time."""
    start_point_value: int | None = None
    end_point_value: int | None = None
    control_point_value: int | None = None
    control_point_relative_time: int | None = None    # Q0.8, 0..255


@dataclass
class MixGainParameterData:
    """MixGainParameterData() (v2:2464-2467); the gain values are Q7.8 dB."""
    animation_type: int
    gain: AnimatedValue


@dataclass
class DemixingInfoParameterData:
    """DemixingInfoParameterData() (v2:2483-2486); dmixp_mode 3 and 7 are
    reserved (v2:2493-2500)."""
    dmixp_mode: int
    reserved: int


@dataclass
class ReconGainLayerData:
    """recon_gain_flags(i) and the recon_gain of each flagged channel for one
    layer of a scalable channel element (v2:2518-2528). The gains are keyed
    by bit position (b0 Left .. b11 LFE, v2:2535-2550)."""
    recon_gain_flags: int
    recon_gains: dict[int, int] = field(default_factory=dict)


@dataclass
class ReconGainInfoParameterData:
    """One entry per ChannelAudioLayerConfig() of the element, in layer
    order; None for a layer whose recon_gain_is_present_flag is 0."""
    layers: list[ReconGainLayerData | None] = field(default_factory=list)


@dataclass
class PositionParameterData:
    """PolarParameterData() .. DualCart16ParameterData() (v2:2586-2813).
    One triple per object, in syntax order: (azimuth, elevation, distance)
    for the polar types, (x, y, z) for the Cartesian ones, each an
    AnimatedValue in the units of the definition's defaults."""
    animation_type: int
    objects: list[tuple[AnimatedValue, AnimatedValue, AnimatedValue]] = field(
        default_factory=list)


@dataclass
class MomentaryLoudnessParameterData:
    """MomentaryLoudnessParameterData() (v2:2840-2843): the loudness is
    -1 x momentary_loudness LKFS."""
    momentary_loudness: int
    reserved: int


@dataclass
class ParameterSubblock:
    # subblock_duration as coded in the block: only in mode 1 with
    # constant_subblock_duration 0 (v2:2298-2301); None otherwise.
    subblock_duration: int | None = None
    data: (MixGainParameterData | DemixingInfoParameterData
           | ReconGainInfoParameterData | PositionParameterData
           | MomentaryLoudnessParameterData | None) = None


@dataclass
class ParameterBlock:
    """A Parameter Block OBU (v2:2281-2335), read by the first declaration of
    its parameter_id in the registry. The block-level duration fields are
    kept as coded, which is only in param_definition_mode 1; in mode 0 they
    come from the definition (parameter_block_timing() joins the two).

    payload_read is False when the payload could not be read to the end:
    no declaration for the id, a definition type without parameter data
    syntax, an undefined animation_type, a truncated or overrunning payload.
    read_error says which; the subblocks read before it are kept."""
    parameter_id: int
    header: OBUHeader
    param_definition_type: int | None = None
    param_definition_mode: int | None = None
    duration: int | None = None
    constant_subblock_duration: int | None = None
    num_subblocks: int | None = None        # coded only when constant_subblock_duration is 0
    subblocks: list[ParameterSubblock] = field(default_factory=list)
    payload_read: bool = False
    read_error: str | None = None
    extra_bytes: int = 0                    # payload bytes after the syntax


@dataclass
class IAMFModel:
    sequence_header: SequenceHeader | None = None
    codec_configs: dict[int, CodecConfig] = field(default_factory=dict)
    audio_elements: dict[int, AudioElement] = field(default_factory=dict)
    mix_presentations: list[MixPresentation] = field(default_factory=list)
    obu_order: list[str] = field(default_factory=list)   # OBU type names, in file order
    audio_frames: list[AudioFrameRef] = field(default_factory=list)
    parameter_block_ids: list[int] = field(default_factory=list)
    # Every Parameter Block OBU, in file order, with its payload as read.
    parameter_blocks: list[ParameterBlock] = field(default_factory=list)
    # The parameter-definition registry: parameter_id -> every declaration
    # of it in the descriptors, in file order (ParamDeclaration).
    parameter_definitions: dict[int, list[ParamDeclaration]] = field(default_factory=dict)
    # is_not_key_frame of every Temporal Delimiter OBU, in file order (IAMF
    # v2.0.0: True = the temporal unit it opens is not a key frame).
    temporal_delimiter_is_not_key_frame: list[bool] = field(default_factory=list)
    # descriptor byte span (for container/size reporting)
    descriptor_bytes: int = 0
    source: str = ""
    container: str = "raw"          # "raw" | "mp4"
    # non-fatal parse notes captured while reading (surfaced as INFO/L1)
    parse_notes: list[str] = field(default_factory=list)
    # The subset of parse_notes that record a genuine ParseError. S-108 reads
    # this list, not the wording: forward-compat skips and "not modelled"
    # notes appear in parse_notes only and are never findings.
    parse_errors: list[str] = field(default_factory=list)
