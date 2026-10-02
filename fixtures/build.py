"""Clean-room IAMF serialiser for fixtures + mutation testing.

Produces spec-valid IAMF descriptor OBUs (plus a couple of temporal units of
LPCM frames) from a structured spec dict, so tests can build known-good files
and mutate individual fields deterministically. Written from the same spec as
the parser; deliberately independent of it (round-trip = differential test).

Uses LPCM ('ipcm') essence so no real codec payload is needed.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# -- low-level writer -------------------------------------------------------
class Writer:
    def __init__(self):
        self.b = bytearray()

    def u8(self, v): self.b.append(v & 0xFF); return self
    def u16(self, v): self.b += (v & 0xFFFF).to_bytes(2, "big"); return self
    def s16(self, v): self.b += (v & 0xFFFF).to_bytes(2, "big"); return self
    def u32(self, v): self.b += (v & 0xFFFFFFFF).to_bytes(4, "big"); return self
    def fourcc(self, s): self.b += s.encode("latin-1"); return self
    def raw(self, data): self.b += data; return self

    def leb128(self, v):
        if v < 0:
            raise ValueError("leb128 negative")
        while True:
            byte = v & 0x7F
            v >>= 7
            if v:
                self.b.append(byte | 0x80)
            else:
                self.b.append(byte)
                break
        return self

    def cstring(self, s):
        self.b += s.encode("utf-8") + b"\x00"
        return self

    def bytes(self):
        return bytes(self.b)


class BitWriter:
    """MSB-first bit packer for the position parameter data, whose fields
    are not byte-aligned (signed 9 / signed 8 / unsigned 7 bits in a row)."""

    def __init__(self):
        self.bits: list[int] = []

    def u(self, v, width):
        for i in range(width - 1, -1, -1):
            self.bits.append((v >> i) & 1)
        return self

    def s(self, v, width):
        return self.u(v & ((1 << width) - 1), width)

    def bytes(self) -> bytes:
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8))


def q78(db: float) -> int:
    return int(round(db * 256.0))


def obu(obu_type: int, payload: bytes, *, trim_start: int = 0,
        trim_end: int = 0, flag: bool = False, redundant: bool = False) -> bytes:
    """OBU framing. Non-zero trim_* sets trimming_status_flag and writes the
    num_samples_to_trim_at_end / _at_start leb128 fields (spec order).

    flag sets the same header bit with no fields after it: the bit is
    optional_fields_flag on a Mix Presentation and is_not_key_frame on a
    Temporal Delimiter (IAMF v2.0.0 OBUHeader()). redundant sets
    obu_redundant_copy."""
    w = Writer()
    trimming = 1 if (trim_start or trim_end) else 0
    w.u8(((obu_type & 0x1F) << 3) | (int(redundant) << 2)
         | ((trimming | int(flag)) << 1))
    fields = b""
    if trimming:
        fields = Writer().leb128(trim_end).leb128(trim_start).bytes()
    w.leb128(len(fields) + len(payload))
    w.raw(fields)
    w.raw(payload)
    return w.bytes()


# -- structured spec --------------------------------------------------------
@dataclass
class ChannelLayerSpec:
    loudspeaker_layout: int
    substream_count: int
    coupled_substream_count: int
    expanded: int | None = None


@dataclass
class ParamDefSpec:
    """A ParamDefinition() with every field under the test's control.

    ptype 0 MIX_GAIN (writes default_mix_gain), 1 DEMIXING (writes the
    demixing defaults), 2 RECON_GAIN, 9 MOMENTARY_LOUDNESS. mode 0 writes
    duration and constant_subblock_duration; with constant_subblock_duration
    0 it writes num_subblocks and the subblock_durations too."""
    ptype: int
    parameter_id: int = 1000
    rate: int = 48000
    mode: int = 1
    duration: int | None = None
    constant_subblock_duration: int | None = None
    subblock_durations: list[int] = field(default_factory=list)
    num_subblocks: int | None = None          # forced count (default: the list's length)
    default_mix_gain: int = 0                 # Q7.8
    default_dmixp_mode: int = 0
    default_w: int = 0
    reserved: int = 0                         # the 7 bits after param_definition_mode

    def write(self, w: "Writer", *, with_type: bool = True) -> None:
        if with_type:
            w.leb128(self.ptype)
        w.leb128(self.parameter_id).leb128(self.rate)
        w.u8(((self.mode & 1) << 7) | (self.reserved & 0x7F))
        if self.mode == 0:
            w.leb128(self.duration or 0).leb128(self.constant_subblock_duration or 0)
            if not self.constant_subblock_duration:
                n = (len(self.subblock_durations) if self.num_subblocks is None
                     else self.num_subblocks)
                w.leb128(n)
                for d in self.subblock_durations:
                    w.leb128(d)
        if self.ptype == 1:
            w.u8((self.default_dmixp_mode & 0x7) << 5).u8((self.default_w & 0xF) << 4)
        if self.ptype == 0:
            w.s16(self.default_mix_gain)


# -- parameter data of one subblock, by definition type (IAMF v2.0.0) ------
def mix_gain_data(animation_type: int, start: int | None = None, end: int | None = None,
                  control: int | None = None, time: int | None = None) -> bytes:
    """MixGainParameterData(): animation_type then AnimatedParameterData<s16>.
    Pass exactly the values the animation type carries (0 STEP: start;
    1 LINEAR: start, end; 2 BEZIER: start, end, control, time; 3 INTER_LINEAR:
    end; 4 INTER_BEZIER: end, control, time); a value passed for a field the
    type does not carry is written anyway (a malformed block on purpose)."""
    w = Writer().leb128(animation_type)
    for v in (start, end, control):
        if v is not None:
            w.s16(v)
    if time is not None:
        w.u8(time)
    return w.bytes()


def demixing_data(dmixp_mode: int, reserved: int = 0) -> bytes:
    return bytes([((dmixp_mode & 0x7) << 5) | (reserved & 0x1F)])


def recon_gain_data(layers: list) -> bytes:
    """ReconGainInfoParameterData(): one entry per layer whose
    recon_gain_is_present_flag is set, each (recon_gain_flags, {bit: gain})
    or a raw int flags value with no gains. The flags leb128 is written as
    given; the gains follow in bit order."""
    w = Writer()
    for flags, gains in layers:
        w.leb128(flags)
        for bit in sorted(gains):
            w.u8(gains[bit])
    return w.bytes()


def momentary_loudness_data(momentary_loudness: int, reserved: int = 0) -> bytes:
    return bytes([((momentary_loudness & 0x3F) << 2) | (reserved & 0x3)])


_POSITION_WIDTHS = {3: (9, 8, 7), 6: (9, 8, 7), 4: (8, 8, 8), 7: (8, 8, 8),
                    5: (16, 16, 16), 8: (16, 16, 16)}


def position_data(ptype: int, animation_type: int, objects: list) -> bytes:
    """PolarParameterData() .. DualCart16ParameterData(): animation_type, then
    per object three AnimatedParameterData instances bit-packed in sequence.
    Each object is a triple of per-axis values; an axis value is an int for
    STEP / INTER_LINEAR (the one value the type carries) or a tuple of the
    values the type carries, in template order (start, end, control, time)."""
    w = Writer().leb128(animation_type)
    bits = BitWriter()
    widths = _POSITION_WIDTHS[ptype]
    for triple in objects:
        for k, (axis, width) in enumerate(zip(triple, widths)):
            values = axis if isinstance(axis, tuple) else (axis,)
            n_values = {0: 1, 1: 2, 2: 3, 3: 1, 4: 2}.get(animation_type, len(values))
            for i, v in enumerate(values):
                if i >= n_values:
                    bits.u(v, 8)                   # control_point_relative_time
                elif k == 2 and ptype in (3, 6):
                    bits.u(v, width)               # polar distance is unsigned
                else:
                    bits.s(v, width)
    return w.raw(bits.bytes()).bytes()


@dataclass
class SubblockSpec:
    data: bytes                               # one of the *_data() helpers, or raw
    duration: int | None = None               # written when the block is mode 1 with csd 0


@dataclass
class ParameterBlockSpec:
    """One Parameter Block OBU, placed at the start of temporal unit `tu`
    (after its Temporal Delimiter, before its audio frames). mode1 writes
    duration, constant_subblock_duration and, with the latter 0,
    num_subblocks (the subblock count unless forced). raw replaces the
    whole payload after parameter_id."""
    parameter_id: int
    tu: int = 0
    mode1: tuple | None = None                # (duration, constant_subblock_duration)
    num_subblocks: int | None = None          # forced count written when csd == 0
    subblocks: list[SubblockSpec] = field(default_factory=list)
    raw: bytes | None = None
    trailing: bytes = b""                     # bytes after the syntax, inside obu_size
    redundant: bool = False
    truncate: int | None = None               # keep only this many payload bytes

    def bytes(self) -> bytes:
        w = Writer().leb128(self.parameter_id)
        if self.raw is not None:
            w.raw(self.raw)
        else:
            csd = None
            if self.mode1 is not None:
                duration, csd = self.mode1
                w.leb128(duration).leb128(csd)
                if csd == 0:
                    w.leb128(len(self.subblocks) if self.num_subblocks is None
                             else self.num_subblocks)
            for sb in self.subblocks:
                if self.mode1 is not None and csd == 0 and sb.duration is not None:
                    w.leb128(sb.duration)
                w.raw(sb.data)
            w.raw(self.trailing)
        payload = w.bytes()
        if self.truncate is not None:
            payload = payload[: self.truncate]
        return obu(3, payload, redundant=self.redundant)


@dataclass
class ElementSpec:
    id: int
    codec_config_id: int
    kind: str                       # "channel" | "scene" | "object"
    substream_ids: list[int]
    layers: list[ChannelLayerSpec] = field(default_factory=list)
    ambi_order: int | None = None
    ambi_mapping: list[int] | None = None
    ambi_substream_count: int | None = None
    ambi_occ_override: int | None = None      # force a non-(N+1)^2 output_channel_count
    # (ptype, rate) for a mode-1 definition of parameter_id 1000, or a
    # ParamDefSpec for one with every field chosen.
    params: list = field(default_factory=list)
    # kind "object": ObjectsConfig() = objects_config_size, num_objects, then
    # objects_extension as objects_config_extension_bytes.
    num_objects: int = 1
    objects_extension: bytes = b""
    # Written in place of the element's config, whatever the kind: lets a test
    # put bytes there that are not the config the type calls for.
    raw_config: bytes | None = None
    audio_element_type: int | None = None     # force the 3-bit type (reserved values)
    # When set, every frame of this element's substreams is a whole LPCM frame
    # of that many channels (num_samples_per_frame x channels x 3 bytes, the
    # fixture codec being 24-bit). When None the frame is the 8-byte
    # placeholder every other fixture uses, which is no whole LPCM frame.
    frame_channels: int | None = None


@dataclass
class MomentarySpec:
    """The momentary-loudness part of a LoudnessInfo() (info_type bit 3):
    a MomentaryLoudnessParamDefinition() and the histogram fields."""
    definition: ParamDefSpec
    num_bin_pairs_minus_one: int = 0
    bin_width_minus_one: int = 0
    first_bin_center: int = 0
    counts: list[int] = field(default_factory=lambda: [0, 0])
    reserved: int = 0


@dataclass
class LayoutSpec:
    sound_system: int
    integrated_db: float
    digital_db: float
    true_peak_db: float | None = None
    # info_type bits 2..4 and the info_type_size envelope they share.
    live: bool = False                          # bit 2, no syntax of its own
    momentary: MomentarySpec | None = None      # bit 3
    loudness_range: int | None = None           # bit 4
    info_type_bytes: bytes = b""                # reserved tail of the envelope
    info_type_raw: bytes | None = None          # the whole envelope, verbatim


def polar_bytes(azimuth: int, elevation: int, distance: int) -> bytes:
    """One object's default polar position: signed 9-bit azimuth, signed 8-bit
    elevation, unsigned 7-bit distance, MSB first (PolarParamDefinition())."""
    v = ((azimuth & 0x1FF) << 15) | ((elevation & 0xFF) << 7) | (distance & 0x7F)
    return v.to_bytes(3, "big")


@dataclass
class PositionSpec:
    """A position-based parameter definition inside a RenderingConfig().

    ptype 3 POLAR, 4 CART8, 5 CART16, 6 DUAL_POLAR, 7 DUAL_CART8,
    8 DUAL_CART16. defaults holds one (a, b, c) triple per object, coded
    values: (azimuth, elevation, distance) or (x, y, z)."""
    ptype: int
    defaults: list[tuple[int, int, int]]
    parameter_id: int = 2000
    rate: int = 48000

    def bytes(self) -> bytes:
        w = Writer().leb128(self.ptype)
        w.leb128(self.parameter_id).leb128(self.rate).u8(0x80)    # mode 1
        for a, b, c in self.defaults:
            if self.ptype in (3, 6):
                w.raw(polar_bytes(a, b, c))
            elif self.ptype in (4, 7):
                w.u8(a).u8(b).u8(c)
            else:
                w.s16(a).s16(b).s16(c)
        return w.bytes()


@dataclass
class RenderingSpec:
    """RenderingConfig() of one element of a sub-mix (IAMF v2.0.0).

    The default is the v1.1.0 form: mode 0, an empty extension envelope. The
    envelope is written, with num_parameters first, as soon as there is
    anything to put in it."""
    headphones_rendering_mode: int = 0
    binaural_filter_profile: int = 0
    reserved: int = 0                              # the 3 reserved bits
    # In file order: a PositionSpec, or (param_definition_type, bytes) for a
    # definition carried as param_definition_size + param_definition_bytes.
    params: list = field(default_factory=list)
    # ("value", q78) | ("range", default, min, max) | (type, bytes) for a
    # reserved element_gain_offset_type carried as size + bytes.
    gain_offset: tuple | None = None
    gain_offset_flag: bool | None = None           # force the flag bit
    extension_bytes: bytes = b""                   # rendering_config_extension_bytes
    write_num_parameters: bool = False             # num_parameters = 0 on its own
    raw_extension: bytes | None = None             # the whole envelope, verbatim

    def bytes(self) -> bytes:
        flag = (self.gain_offset is not None if self.gain_offset_flag is None
                else self.gain_offset_flag)
        w = Writer().u8(((self.headphones_rendering_mode & 0x3) << 6) | (int(flag) << 5)
                        | ((self.binaural_filter_profile & 0x3) << 3)
                        | (self.reserved & 0x7))
        ext = Writer()
        if self.raw_extension is not None:
            ext.raw(self.raw_extension)
        elif (self.params or self.gain_offset is not None or self.extension_bytes
              or self.write_num_parameters):
            ext.leb128(len(self.params))
            for p in self.params:
                if isinstance(p, PositionSpec):
                    ext.raw(p.bytes())
                else:
                    ptype, body = p
                    ext.leb128(ptype).leb128(len(body)).raw(body)
            if self.gain_offset is not None:
                kind, *vals = self.gain_offset
                if kind == "value":
                    ext.u8(0).s16(vals[0])
                elif kind == "range":
                    ext.u8(1).s16(vals[0]).s16(vals[1]).s16(vals[2])
                else:
                    ext.u8(kind).leb128(len(vals[0])).raw(vals[0])
            ext.raw(self.extension_bytes)
        return w.leb128(len(ext.b)).raw(ext.bytes()).bytes()


@dataclass
class MixSpec:
    id: int
    ae_ids: list[int]
    annotation: str
    layouts: list[LayoutSpec]
    # (preferred_loudspeaker_renderer, preferred_binaural_renderer): writes the
    # tags + optional fields tail and sets optional_fields_flag in the header.
    optional_fields: tuple[int, int] | None = None
    tags: list[tuple[str, str]] = field(default_factory=list)
    optional_fields_remaining: bytes = b""    # optional_fields_remaining_bytes
    # Sub-mixes after the first (ae_ids is the first): one list of audio
    # element ids each. Every sub-mix carries the same loudness layouts.
    extra_sub_mixes: list[list[int]] = field(default_factory=list)
    # audio_element_id -> its RenderingConfig(); an element not listed gets
    # the v1.1.0 form (mode 0, empty extension).
    rendering: dict[int, RenderingSpec] = field(default_factory=dict)
    # audio_element_id -> its element_mix_gain, and the output_mix_gain of
    # every sub-mix; unlisted ones are mode-1 definitions of parameter_id
    # 1000 at 48000/s with default_mix_gain 0.
    element_mix_gains: dict[int, ParamDefSpec] = field(default_factory=dict)
    output_mix_gain: ParamDefSpec | None = None


@dataclass
class IAMFSpec:
    primary_profile: int = 1
    additional_profile: int = 1
    codec_config_id: int = 0
    codec_id: str = "ipcm"
    num_samples_per_frame: int = 480
    elements: list[ElementSpec] = field(default_factory=list)
    mixes: list[MixSpec] = field(default_factory=list)
    temporal_units: int = 2
    extra_frames: list[int] = field(default_factory=list)   # spurious substream ids
    drop_frame_substreams: list[int] = field(default_factory=list)  # declared but no frames
    truncate_to: int | None = None
    trim_start_first_tu: int = 0      # num_samples_to_trim_at_start on TU 0 frames
    trim_end_last_tu: int = 0         # num_samples_to_trim_at_end on last-TU frames
    temporal_delimiters: bool = False             # a Temporal Delimiter opens every TU
    non_key_tus: list[int] = field(default_factory=list)   # TUs with is_not_key_frame=1
    # Parameter Block OBUs, each placed at the start of its temporal unit
    # (after the Temporal Delimiter, before the audio frames), in list order.
    parameter_blocks: list[ParameterBlockSpec] = field(default_factory=list)
    # Further Codec Config OBUs after the first, as (codec_config_id, codec_id).
    extra_codec_configs: list[tuple[int, str]] = field(default_factory=list)
    # Copies of the first Codec Config OBU with obu_redundant_copy set, each
    # followed inside the OBU by redundant_codec_config_padding (bytes past
    # the syntax, which obu_size may cover and parsers ignore).
    redundant_codec_configs: int = 0
    redundant_codec_config_padding: bytes = b""

    def copy(self) -> "IAMFSpec":
        import copy as _c
        return _c.deepcopy(self)


# -- serialise --------------------------------------------------------------
def _codec_config(spec: IAMFSpec, *, codec_config_id: int | None = None,
                  codec_id: str | None = None, redundant: bool = False,
                  padding: bytes = b"") -> bytes:
    codec_id = spec.codec_id if codec_id is None else codec_id
    w = Writer()
    w.leb128(spec.codec_config_id if codec_config_id is None else codec_config_id)
    w.fourcc(codec_id)
    w.leb128(spec.num_samples_per_frame)
    w.s16(0)                          # audio_roll_distance
    if codec_id == "ipcm":
        w.u8(1)                       # sample_format_flags (little endian)
        w.u8(24)                      # sample_size
        w.u32(48000)                  # sample_rate
    elif codec_id == "Opus":
        w.u8(1).u8(2).u16(312).u32(48000).s16(0).u8(0)
    return obu(0, w.bytes() + padding, redundant=redundant)


def _param_definition(w: Writer, ptype: int | None, rate: int, mix_gain: bool):
    # ptype prefix only inside an audio element's parameter loop
    if ptype is not None:
        w.leb128(ptype)
    w.leb128(1000)                    # parameter_id
    w.leb128(rate)                    # parameter_rate
    w.u8(0x80)                        # param_definition_mode=1, reserved
    if ptype == 1:                    # demixing default fields (spec type 1)
        w.u8(0).u8(0)
    if mix_gain:
        w.s16(0)


def _mix_gain_definition(w: Writer, spec: ParamDefSpec | None) -> None:
    if spec is None:
        _param_definition(w, None, 48000, mix_gain=True)
    else:
        spec.write(w, with_type=False)


def _audio_element(e: ElementSpec) -> bytes:
    w = Writer()
    w.leb128(e.id)
    ae_type = (e.audio_element_type if e.audio_element_type is not None
               else 0 if e.kind == "channel" else 2 if e.kind == "object" else 1)
    w.u8((ae_type & 0x7) << 5)
    w.leb128(e.codec_config_id)
    w.leb128(len(e.substream_ids))
    for sid in e.substream_ids:
        w.leb128(sid)
    w.leb128(len(e.params))
    for p in e.params:
        if isinstance(p, ParamDefSpec):
            p.write(w)
        else:
            ptype, rate = p
            _param_definition(w, ptype, rate, mix_gain=False)
    if e.raw_config is not None:
        w.raw(e.raw_config)
    elif e.kind == "object":
        w.leb128(1 + len(e.objects_extension))    # objects_config_size
        w.u8(e.num_objects)
        w.raw(e.objects_extension)
    elif e.kind == "channel":
        w.u8((len(e.layers) & 0x7) << 5)
        for layer in e.layers:
            lsl = layer.loudspeaker_layout
            w.u8((lsl & 0xF) << 4)    # loudspeaker_layout, no gain flags
            w.u8(layer.substream_count)
            w.u8(layer.coupled_substream_count)
            if lsl == 15 and layer.expanded is not None:
                w.u8(layer.expanded)
    else:
        occ = e.ambi_occ_override if e.ambi_occ_override is not None else (e.ambi_order + 1) ** 2
        mapping = e.ambi_mapping if e.ambi_mapping is not None else list(range(occ))
        scount = e.ambi_substream_count if e.ambi_substream_count is not None else occ
        w.leb128(0)                   # ambisonics_mode MONO
        w.u8(occ)
        w.u8(scount)
        for x in mapping:
            w.u8(x)
    return obu(1, w.bytes())


def _mix_presentation(mx: MixSpec, count_label: int = 1) -> bytes:
    w = Writer()
    w.leb128(mx.id)
    w.leb128(count_label)
    for _ in range(count_label):
        w.cstring("en-us")
    for _ in range(count_label):
        w.cstring(mx.annotation)
    w.leb128(1 + len(mx.extra_sub_mixes))                  # num_sub_mixes
    for ae_ids in [mx.ae_ids] + mx.extra_sub_mixes:
        w.leb128(len(ae_ids))         # num_audio_elements
        for ae_id in ae_ids:
            w.leb128(ae_id)
            for _ in range(count_label):
                w.cstring("element")
            w.raw(mx.rendering.get(ae_id, RenderingSpec()).bytes())  # rendering_config
            _mix_gain_definition(w, mx.element_mix_gains.get(ae_id))  # element_mix_gain
        _mix_gain_definition(w, mx.output_mix_gain)                   # output_mix_gain
        w.leb128(len(mx.layouts))
        for ly in mx.layouts:
            info_type = 1 if ly.true_peak_db is not None else 0
            info_type |= (4 if ly.live else 0) | (8 if ly.momentary else 0)
            info_type |= 16 if ly.loudness_range is not None else 0
            w.u8((2 << 6) | ((ly.sound_system & 0xF) << 2))    # SS convention
            w.u8(info_type)
            w.s16(q78(ly.integrated_db))
            w.s16(q78(ly.digital_db))
            if info_type & 1:
                w.s16(q78(ly.true_peak_db))
            if info_type & 0xFC or ly.info_type_raw is not None:
                env = Writer()
                if ly.info_type_raw is not None:
                    env.raw(ly.info_type_raw)
                else:
                    if ly.momentary is not None:
                        ml = ly.momentary
                        ml.definition.write(env, with_type=False)
                        env.u16(((ml.num_bin_pairs_minus_one & 0x7) << 13)
                                | ((ml.bin_width_minus_one & 0x3F) << 7)
                                | ((ml.first_bin_center & 0x3F) << 1) | (ml.reserved & 1))
                        for c in ml.counts:
                            env.leb128(c)
                    if ly.loudness_range is not None:
                        env.u8((ly.loudness_range & 0x3F) << 2)
                    env.raw(ly.info_type_bytes)
                w.leb128(len(env.b)).raw(env.bytes())
    if mx.optional_fields is None:
        return obu(2, w.bytes())
    w.u8(len(mx.tags))                # MixPresentationTags precede the optional fields
    for name, value in mx.tags:
        w.cstring(name).cstring(value)
    w.leb128(2 + len(mx.optional_fields_remaining))        # optional_fields_size
    w.u8(mx.optional_fields[0]).u8(mx.optional_fields[1])
    w.raw(mx.optional_fields_remaining)
    return obu(2, w.bytes(), flag=True)


def _audio_frames(spec: IAMFSpec) -> bytes:
    out = bytearray()
    declared = []
    for e in spec.elements:
        declared.extend(e.substream_ids)
    declared = [s for s in declared if s not in spec.drop_frame_substreams]
    pcm = b"\x00" * 8
    whole = {sid: b"\x00" * (spec.num_samples_per_frame * e.frame_channels * 3)
             for e in spec.elements if e.frame_channels is not None
             for sid in e.substream_ids}
    for _tu in range(spec.temporal_units):
        ts = spec.trim_start_first_tu if _tu == 0 else 0
        te = spec.trim_end_last_tu if _tu == spec.temporal_units - 1 else 0
        if spec.temporal_delimiters:
            out += obu(4, b"", flag=_tu in spec.non_key_tus)
        for pb in spec.parameter_blocks:
            if pb.tu == _tu:
                out += pb.bytes()
        for sid in declared:
            payload = Writer().leb128(sid).raw(whole.get(sid, pcm)).bytes()
            out += obu(5, payload, trim_start=ts, trim_end=te)
        for sid in spec.extra_frames:
            payload = Writer().leb128(sid).raw(pcm).bytes()
            out += obu(5, payload, trim_start=ts, trim_end=te)
    return bytes(out)


def build(spec: IAMFSpec) -> bytes:
    out = bytearray()
    out += obu(31, Writer().fourcc("iamf").u8(spec.primary_profile)
               .u8(spec.additional_profile).bytes())       # sequence header
    out += _codec_config(spec)
    for _ in range(spec.redundant_codec_configs):
        out += _codec_config(spec, redundant=True,
                             padding=spec.redundant_codec_config_padding)
    for cc_id, codec_id in spec.extra_codec_configs:
        out += _codec_config(spec, codec_config_id=cc_id, codec_id=codec_id)
    for e in spec.elements:
        out += _audio_element(e)
    for mx in spec.mixes:
        out += _mix_presentation(mx)
    out += _audio_frames(spec)
    data = bytes(out)
    if spec.truncate_to is not None:
        data = data[: spec.truncate_to]
    return data


# -- library of valid specs -------------------------------------------------
# (loudspeaker_layout, substreams, coupled, sound_system, channels)
# sound_system per corrected SOUND_SYSTEM table: 5.1=B(1), 7.1=I(8), 7.1.4=J(9).
_CHANNEL_LAYOUTS = {
    "mono":  (0, 1, 0, 0, 1),      # mono has no SS layout of its own; stereo loudness used
    "stereo": (1, 1, 1, 0, 2),
    "5.1":   (2, 4, 2, 1, 6),
    "7.1":   (5, 5, 3, 8, 8),
    "7.1.4": (7, 7, 5, 9, 12),
}


def channel_spec(name: str, *, profile: int = 1) -> IAMFSpec:
    lsl, sub, coup, ss, _ch = _CHANNEL_LAYOUTS[name]
    ids = list(range(sub))
    layouts = [LayoutSpec(0, -18.0, -6.0)]                 # stereo loudness
    if ss != 0:
        layouts.append(LayoutSpec(ss, -20.0, -8.0))        # native loudness (avoids F23)
    return IAMFSpec(
        primary_profile=profile, additional_profile=profile,
        elements=[ElementSpec(300, 0, "channel", ids,
                              layers=[ChannelLayerSpec(lsl, sub, coup)])],
        mixes=[MixSpec(42, [300], "Fixture Program", layouts)],
    )


def scene_spec(order: int, *, profile: int = 1) -> IAMFSpec:
    occ = (order + 1) ** 2
    ids = list(range(occ))
    layouts = [LayoutSpec(0, -18.0, -6.0), LayoutSpec(1, -19.0, -7.0),
               LayoutSpec(9, -20.0, -8.0)]                 # stereo+5.1+7.1.4 (J=9)
    return IAMFSpec(
        primary_profile=profile, additional_profile=profile,
        elements=[ElementSpec(300, 0, "scene", ids, ambi_order=order)],
        mixes=[MixSpec(42, [300], "Fixture Ambisonics", layouts)],
    )


def object_spec(*, dual: bool = False, ptype: int | None = None,
                profile: int = 4) -> IAMFSpec:
    """One object-based element (one object, or two with dual=True) and the
    position definition its rendering_config has to carry. ptype defaults to
    POLAR (3) or DUAL_POLAR (6); pass 4/5 or 7/8 for the Cartesian forms. Its
    frames are whole LPCM frames, mono for one object and stereo for two."""
    if ptype is None:
        ptype = 6 if dual else 3
    if ptype in (3, 6):
        defaults = [(30, 10, 127), (-30, 10, 127)]         # azimuth, elevation, distance
    elif ptype in (4, 7):
        defaults = [(-64, 127, 0), (64, 127, 0)]           # x, y, z in 1/127
    else:
        defaults = [(-16384, 32767, 0), (16384, 32767, 0)]   # x, y, z in 1/32767
    defaults = defaults[: 2 if ptype >= 6 else 1]
    layouts = [LayoutSpec(0, -18.0, -6.0), LayoutSpec(1, -19.0, -7.0)]
    n = 2 if dual else 1
    return IAMFSpec(
        primary_profile=profile, additional_profile=profile,
        num_samples_per_frame=8,       # short whole frames: 24 or 48 bytes each
        elements=[ElementSpec(300, 0, "object", [0], num_objects=n, frame_channels=n)],
        mixes=[MixSpec(42, [300], "Fixture Objects", layouts,
                       rendering={300: RenderingSpec(
                           headphones_rendering_mode=1,
                           params=[PositionSpec(ptype, defaults)])})],
    )


def animated_spec() -> IAMFSpec:
    """A 5.1 stream whose parameters move: a demixing definition on the
    element (mode 0, one frame per block), an element_mix_gain in mode 1 and
    an output_mix_gain in mode 0, each with a Parameter Block OBU at the head
    of every temporal unit. parameter_rate equals the 48000 Hz sample rate,
    so one frame of 480 samples is 480 ticks."""
    spec = channel_spec("5.1")
    spec.elements[0].params = [ParamDefSpec(1, parameter_id=200, mode=0, duration=480,
                                            constant_subblock_duration=480,
                                            default_dmixp_mode=1, default_w=10)]
    mx = spec.mixes[0]
    mx.element_mix_gains = {300: ParamDefSpec(0, parameter_id=100, default_mix_gain=q78(-3.0))}
    mx.output_mix_gain = ParamDefSpec(0, parameter_id=101, mode=0, duration=480,
                                      constant_subblock_duration=480)
    for tu in range(spec.temporal_units):
        spec.parameter_blocks += [
            ParameterBlockSpec(100, tu, mode1=(480, 480),
                               subblocks=[SubblockSpec(mix_gain_data(0, q78(-3.0 - tu)))]),
            ParameterBlockSpec(101, tu, subblocks=[SubblockSpec(
                mix_gain_data(1, q78(-1.0 * tu), q78(-1.0 * (tu + 1))))]),
            ParameterBlockSpec(200, tu, subblocks=[SubblockSpec(demixing_data(1 + tu))]),
        ]
    return spec


def all_valid_specs() -> dict[str, IAMFSpec]:
    d = {name: channel_spec(name) for name in _CHANNEL_LAYOUTS}
    d["foa"] = scene_spec(1)
    d["3oa"] = scene_spec(3)
    d["object"] = object_spec()
    d["dual-object"] = object_spec(dual=True)
    d["animated"] = animated_spec()
    return d
