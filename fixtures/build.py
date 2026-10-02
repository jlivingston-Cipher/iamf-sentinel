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
    params: list[tuple[int, int]] = field(default_factory=list)  # (ptype, rate)
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
class LayoutSpec:
    sound_system: int
    integrated_db: float
    digital_db: float
    true_peak_db: float | None = None


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
    for ptype, rate in e.params:
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
            _param_definition(w, None, 48000, mix_gain=True)   # element_mix_config
        _param_definition(w, None, 48000, mix_gain=True)       # output_mix_config
        w.leb128(len(mx.layouts))
        for ly in mx.layouts:
            info_type = 1 if ly.true_peak_db is not None else 0
            w.u8((2 << 6) | ((ly.sound_system & 0xF) << 2))    # SS convention
            w.u8(info_type)
            w.s16(q78(ly.integrated_db))
            w.s16(q78(ly.digital_db))
            if info_type & 1:
                w.s16(q78(ly.true_peak_db))
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


def all_valid_specs() -> dict[str, IAMFSpec]:
    d = {name: channel_spec(name) for name in _CHANNEL_LAYOUTS}
    d["foa"] = scene_spec(1)
    d["3oa"] = scene_spec(3)
    d["object"] = object_spec()
    d["dual-object"] = object_spec(dual=True)
    return d
