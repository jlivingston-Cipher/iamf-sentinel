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
        trim_end: int = 0) -> bytes:
    """OBU framing. Non-zero trim_* sets trimming_status_flag and writes the
    num_samples_to_trim_at_end / _at_start leb128 fields (spec order)."""
    w = Writer()
    trimming = 1 if (trim_start or trim_end) else 0
    w.u8(((obu_type & 0x1F) << 3) | (trimming << 1))
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
    kind: str                       # "channel" | "scene"
    substream_ids: list[int]
    layers: list[ChannelLayerSpec] = field(default_factory=list)
    ambi_order: int | None = None
    ambi_mapping: list[int] | None = None
    ambi_substream_count: int | None = None
    ambi_occ_override: int | None = None      # force a non-(N+1)^2 output_channel_count
    params: list[tuple[int, int]] = field(default_factory=list)  # (ptype, rate)


@dataclass
class LayoutSpec:
    sound_system: int
    integrated_db: float
    digital_db: float
    true_peak_db: float | None = None


@dataclass
class MixSpec:
    id: int
    ae_ids: list[int]
    annotation: str
    layouts: list[LayoutSpec]


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

    def copy(self) -> "IAMFSpec":
        import copy as _c
        return _c.deepcopy(self)


# -- serialise --------------------------------------------------------------
def _codec_config(spec: IAMFSpec) -> bytes:
    w = Writer()
    w.leb128(spec.codec_config_id)
    w.fourcc(spec.codec_id)
    w.leb128(spec.num_samples_per_frame)
    w.s16(0)                          # audio_roll_distance
    if spec.codec_id == "ipcm":
        w.u8(1)                       # sample_format_flags (little endian)
        w.u8(24)                      # sample_size
        w.u32(48000)                  # sample_rate
    elif spec.codec_id == "Opus":
        w.u8(1).u8(2).u16(312).u32(48000).s16(0).u8(0)
    return obu(0, w.bytes())


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
    w.u8((0 if e.kind == "channel" else 1) << 5)
    w.leb128(e.codec_config_id)
    w.leb128(len(e.substream_ids))
    for sid in e.substream_ids:
        w.leb128(sid)
    w.leb128(len(e.params))
    for ptype, rate in e.params:
        _param_definition(w, ptype, rate, mix_gain=False)
    if e.kind == "channel":
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
    w.leb128(1)                       # num_sub_mixes
    w.leb128(len(mx.ae_ids))          # num_audio_elements
    for ae_id in mx.ae_ids:
        w.leb128(ae_id)
        for _ in range(count_label):
            w.cstring("element")
        w.u8(0)                       # rendering_config headphones mode + reserved
        w.leb128(0)                   # rendering_config_extension_size
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
    return obu(2, w.bytes())


def _audio_frames(spec: IAMFSpec) -> bytes:
    out = bytearray()
    declared = []
    for e in spec.elements:
        declared.extend(e.substream_ids)
    declared = [s for s in declared if s not in spec.drop_frame_substreams]
    pcm = b"\x00" * 8
    for _tu in range(spec.temporal_units):
        ts = spec.trim_start_first_tu if _tu == 0 else 0
        te = spec.trim_end_last_tu if _tu == spec.temporal_units - 1 else 0
        for sid in declared:
            payload = Writer().leb128(sid).raw(pcm).bytes()
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


def all_valid_specs() -> dict[str, IAMFSpec]:
    d = {name: channel_spec(name) for name in _CHANNEL_LAYOUTS}
    d["foa"] = scene_spec(1)
    d["3oa"] = scene_spec(3)
    return d
