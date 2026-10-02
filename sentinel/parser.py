"""Clean-room IAMF v1.1.0 OBU-stream parser (Sentinel L1 core, ADR-3).

Transcribes the OBU bitstream into model.py dataclasses. Written from the AOM
IAMF specification; no reference-decoder code is used or derived. All reads are
bounds-checked (reader.ParseError) so truncated/fuzzed input never crashes.

Parsing is deliberately separate from validation: this module records what the
bytes say (including structurally-odd values), and the checks/ package renders
judgment. That separation is what lets the F4-class corruption be *seen* — the
descriptor claims one topology while the substreams say another, and only a
parser that faithfully records both can flag the mismatch.
"""

from __future__ import annotations

from .reader import ByteReader, ParseError, split_bits
from . import model as m


# OBU types this parser models for which IAMF v2.0.0 OBUHeader() leaves header
# bit 6 reserved ("SHALL be set to 0", v2:637): Sequence Header, Codec Config,
# Audio Element, Parameter Block. The reserved OBU types 24..30 are left out on
# purpose: they are forward-compatibility skips, and bit 6 is exactly the kind
# of bit a later version gives a meaning to.
_RESERVED_BIT6_TYPES = (m.OBU_SEQUENCE_HEADER, m.OBU_CODEC_CONFIG,
                        m.OBU_AUDIO_ELEMENT, m.OBU_PARAMETER_BLOCK)

# Profiles whose defining specification version is IAMF v2.0.0, and so has
# object-based elements and the v2.0.0 RenderingConfig() syntax
# (Base-Advanced, Advanced-1, Advanced-2; v2:3204, v2:3223, v2:3247).
_OBJECT_PROFILES = (3, 4, 5)


class IAMFParser:
    def __init__(self, data: bytes, *, source: str = "", container: str = "raw") -> None:
        self._r = ByteReader(data)
        self.model = m.IAMFModel(source=source, container=container)
        self._reserved_bit_reported: set[int] = set()
        self._descriptor_end = 0

    # ---------------------------------------------------------------- top level
    def parse(self) -> m.IAMFModel:
        first_frame_seen = False
        while not self._r.eof():
            # OBU framing failures (truncated header/payload) are structured L1
            # findings, never crashes (PRD R1). Stop cleanly at the first bad frame.
            try:
                hdr = self._read_obu_header()
                payload = self._r.subreader(hdr.payload_len)
            except ParseError as e:
                self._parse_error(f"truncated OBU stream: {e}")
                break
            name = m.OBU_TYPE_NAME.get(hdr.obu_type, f"Unknown({hdr.obu_type})")
            self.model.obu_order.append(name)

            t = hdr.obu_type
            if (hdr.reserved_flag and t in _RESERVED_BIT6_TYPES
                    and t not in self._reserved_bit_reported):
                # A SHALL (v2:637), so a parse error for S-108 — once per OBU
                # type, at its first occurrence. The bit adds no fields, so the
                # OBU itself is still read normally below.
                self._reserved_bit_reported.add(t)
                self._parse_error(
                    f"reserved header bit 6 is set on a {name} OBU; IAMF v2.0.0 "
                    f"requires 0 (first at byte {hdr.file_offset})")
            try:
                if t == m.OBU_SEQUENCE_HEADER:
                    self._parse_sequence_header(payload, hdr)
                elif t == m.OBU_CODEC_CONFIG:
                    self._parse_codec_config(payload, hdr)
                elif t == m.OBU_AUDIO_ELEMENT:
                    self._parse_audio_element(payload, hdr)
                elif t == m.OBU_MIX_PRESENTATION:
                    self._parse_mix_presentation(payload, hdr)
                elif t == m.OBU_PARAMETER_BLOCK:
                    self._parse_parameter_block(payload, hdr)
                elif t == m.OBU_TEMPORAL_DELIMITER:
                    self.model.temporal_delimiter_is_not_key_frame.append(
                        hdr.is_not_key_frame)
                elif m.OBU_AUDIO_FRAME <= t <= m.OBU_AUDIO_FRAME_ID17:
                    self._parse_audio_frame(payload, hdr, first_temporal=not first_frame_seen)
                    first_frame_seen = True
                else:
                    self.model.parse_notes.append(
                        f"unknown OBU type {t} at byte {hdr.file_offset} (forward-compat skip)"
                    )
            except ParseError as e:
                # Localised parse failure inside one OBU: record and continue so a
                # single bad descriptor OBU still yields a structured report.
                self._parse_error(f"parse error in {name}: {e}")

            # descriptor span ends at the first audio frame / parameter block
            if t in (m.OBU_SEQUENCE_HEADER, m.OBU_CODEC_CONFIG,
                     m.OBU_AUDIO_ELEMENT, m.OBU_MIX_PRESENTATION):
                self._descriptor_end = self._r.pos
        self.model.descriptor_bytes = self._descriptor_end
        return self.model

    def _parse_error(self, note: str) -> None:
        """Record a genuine ParseError: kept in parse_notes (the ordered log)
        and listed in parse_errors, which is what S-108 reports."""
        self.model.parse_notes.append(note)
        self.model.parse_errors.append(note)

    # ------------------------------------------------------------- OBU framing
    def _read_obu_header(self) -> m.OBUHeader:
        start = self._r.abs_pos
        b0 = self._r.u8()
        obu_type, redundant, bit6, extension = split_bits(b0, 5, 1, 1, 1)
        # Header bit 6 is read per OBU type, as IAMF v2.0.0 OBUHeader() defines
        # it: obu_trimming_status_flag on audio frames (types 5..23),
        # optional_fields_flag on a Mix Presentation, is_not_key_frame on a
        # Temporal Delimiter, reserved otherwise. Only the trimming flag adds
        # header fields. v1.1.0 requires the bit to be 0 outside audio frames,
        # so a conformant v1.1.0 stream reads the same.
        trimming = optional_fields = not_key_frame = reserved = False
        if m.OBU_AUDIO_FRAME <= obu_type <= m.OBU_AUDIO_FRAME_ID17:
            trimming = bool(bit6)
        elif obu_type == m.OBU_MIX_PRESENTATION:
            optional_fields = bool(bit6)
        elif obu_type == m.OBU_TEMPORAL_DELIMITER:
            not_key_frame = bool(bit6)
        else:
            reserved = bool(bit6)
        size = self._r.uleb128()
        trim_end = trim_start = 0
        ext_consumed = 0
        if trimming:
            before = self._r.pos
            trim_end = self._r.uleb128()
            trim_start = self._r.uleb128()
            ext_consumed += self._r.pos - before
        if extension:
            before = self._r.pos
            ext_size = self._r.uleb128()
            self._r.read(ext_size)
            ext_consumed += self._r.pos - before
        payload_len = size - ext_consumed
        if payload_len < 0:
            raise ParseError("obu_size smaller than trimming/extension fields", start)
        return m.OBUHeader(
            obu_type=obu_type, redundant_copy=bool(redundant),
            trimming_status_flag=trimming, extension_flag=bool(extension),
            obu_size=size, num_samples_to_trim_at_end=trim_end,
            num_samples_to_trim_at_start=trim_start, file_offset=start,
            payload_offset=self._r.abs_pos, payload_len=payload_len,
            optional_fields_flag=optional_fields, is_not_key_frame=not_key_frame,
            reserved_flag=reserved,
        )

    # ---------------------------------------------------------------- OBU bodies
    def _parse_sequence_header(self, r: ByteReader, hdr: m.OBUHeader) -> None:
        sh = m.SequenceHeader(
            ia_code=r.fourcc(),
            primary_profile=r.u8(),
            additional_profile=r.u8(),
            header=hdr,
        )
        self.model.sequence_header = sh

    def _parse_codec_config(self, r: ByteReader, hdr: m.OBUHeader) -> None:
        cc_id = r.uleb128()
        codec_id = r.fourcc()
        nspf = r.uleb128()
        roll = r.s16()
        cc = m.CodecConfig(cc_id, codec_id, nspf, roll, header=hdr)
        try:
            if codec_id == "Opus":
                _version = r.u8()
                _out_ch = r.u8()
                cc.opus_pre_skip = r.u16()
                cc.sample_rate = r.u32()
                _out_gain = r.s16()
                cc.opus_mapping_family = r.u8()
                cc.bit_depth = 16
            elif codec_id == "ipcm":
                r.u8()                       # sample_format_flags (bit0: 1=little endian)
                cc.bit_depth = r.u8()        # sample_size
                cc.sample_rate = r.u32()
            elif codec_id == "fLaC":
                # FLAC STREAMINFO metadata block; sample rate in bits [.. ] — best effort skip
                cc.bit_depth = None
            elif codec_id == "mp4a":
                cc.bit_depth = 16
        except ParseError as e:
            self._parse_error(f"codec_config {cc_id} decoder_config: {e}")
        self.model.codec_configs[cc_id] = cc

    def _parse_param_definition(self, r: ByteReader, ptype: int | None,
                                mix_gain: bool) -> m.ParamDefinition:
        parameter_id = r.uleb128()
        parameter_rate = r.uleb128()
        mode_byte = r.u8()
        mode = (mode_byte >> 7) & 1
        pd = m.ParamDefinition(
            param_definition_type=ptype, parameter_id=parameter_id,
            parameter_rate=parameter_rate, param_definition_mode=mode,
            rate_present=parameter_rate != 0,
        )
        if mode == 0:
            pd.duration = r.uleb128()
            pd.constant_subblock_duration = r.uleb128()
            if pd.constant_subblock_duration == 0:
                n = r.uleb128()
                for _ in range(n):
                    r.uleb128()
        if ptype == m.PARAM_DEMIXING:
            r.u8()   # default_demixing_info_parameter_data
            r.u8()   # default_w + reserved
        if mix_gain:
            pd.default_mix_gain = r.s16()
        return pd

    def _parse_audio_element(self, r: ByteReader, hdr: m.OBUHeader) -> None:
        ae_id = r.uleb128()
        type_byte = r.u8()
        ae_type = (type_byte >> 5) & 0x7
        cc_id = r.uleb128()
        num_substreams = r.uleb128()
        substream_ids = [r.uleb128() for _ in range(num_substreams)]
        num_parameters = r.uleb128()
        params: list[m.ParamDefinition] = []
        for _ in range(num_parameters):
            ptype = r.uleb128()
            if ptype in (m.PARAM_DEMIXING, m.PARAM_RECON_GAIN):
                params.append(self._parse_param_definition(r, ptype, mix_gain=False))
            else:
                size = r.uleb128()
                r.read(size)   # reserved param_definition_bytes
        ae = m.AudioElement(
            audio_element_id=ae_id, audio_element_type=ae_type, codec_config_id=cc_id,
            num_substreams=num_substreams, audio_substream_ids=substream_ids,
            parameters=params, header=hdr, num_parameters=num_parameters,
        )
        if ae_type == m.AUDIO_ELEMENT_CHANNEL:
            self._parse_scalable_channel_layout(r, ae)
        elif ae_type == m.AUDIO_ELEMENT_SCENE:
            self._parse_ambisonics_config(r, ae)
        elif ae_type == m.AUDIO_ELEMENT_OBJECT:
            self._parse_objects_config(r, ae)
        else:
            self.model.parse_notes.append(
                f"audio_element {ae_id}: type {ae_type} (reserved) config not modelled"
            )
        self.model.audio_elements[ae_id] = ae

    def _parse_scalable_channel_layout(self, r: ByteReader, ae: m.AudioElement) -> None:
        b = r.u8()
        num_layers = (b >> 5) & 0x7
        for _ in range(num_layers):
            lb = r.u8()
            lsl, og_present, rg_present, _res = split_bits(lb, 4, 1, 1, 2)
            substream_count = r.u8()
            coupled_count = r.u8()
            layer = m.ChannelLayerConfig(
                loudspeaker_layout=lsl, output_gain_is_present=bool(og_present),
                recon_gain_is_present=bool(rg_present), substream_count=substream_count,
                coupled_substream_count=coupled_count,
            )
            # ChannelAudioLayerConfig() order (v2:943-957, v1.1:910-924): the
            # output_gain fields, then expanded_loudspeaker_layout last.
            if og_present:
                ogb = r.u8()
                layer.output_gain_flags = (ogb >> 2) & 0x3F
                layer.output_gain = r.s16()
            if lsl == 15:
                layer.expanded_loudspeaker_layout = r.u8()
            ae.channel_layers.append(layer)

    def _parse_ambisonics_config(self, r: ByteReader, ae: m.AudioElement) -> None:
        from .layouts import order_from_ambisonics_channels
        mode = r.uleb128()
        if mode == 0:  # MONO
            occ = r.u8()
            scount = r.u8()
            mapping = [r.u8() for _ in range(occ)]
            ae.ambisonics = m.AmbisonicsConfig(
                mode=mode, output_channel_count=occ, substream_count=scount,
                channel_mapping=mapping, order=order_from_ambisonics_channels(occ),
                coded_channel_count=scount,
            )
        elif mode == 1:  # PROJECTION
            occ = r.u8()
            scount = r.u8()
            ccount = r.u8()
            # demixing matrix: (scount + ccount) * occ signed-16 coefficients
            for _ in range((scount + ccount) * occ):
                r.s16()
            ae.ambisonics = m.AmbisonicsConfig(
                mode=mode, output_channel_count=occ, substream_count=scount,
                coupled_substream_count=ccount,
                order=order_from_ambisonics_channels(occ),
                coded_channel_count=scount + ccount,
            )
        else:
            self.model.parse_notes.append(f"ambisonics mode {mode} not modelled")

    def _parse_objects_config(self, r: ByteReader, ae: m.AudioElement) -> None:
        """ObjectsConfig() (IAMF v2.0.0): objects_config_size is an envelope
        holding num_objects and then reserved extension bytes, which are
        skipped with the envelope.

        Bytes that do not form an ObjectsConfig leave the element in the
        model with its object count unknown. Whether that is an error depends
        on what the sequence declares. Type 2 was a reserved value before
        v2.0.0, so a stream whose primary_profile and additional_profile are
        both outside 3..5 (or whose Sequence Header has not been read) may
        carry any bytes here: a note. When either profile is one that defines
        object-based elements, the config is required and a truncated,
        zero-size or absent one is a genuine parse error (S-108).
        """
        try:
            size = r.uleb128()
            if size < 1:
                raise ParseError("objects_config_size 0 cannot hold num_objects",
                                 r.abs_pos)
            num_objects = r.subreader(size).u8()
        except ParseError as e:
            note = (f"audio_element {ae.audio_element_id}: type 2 config is not an "
                    f"ObjectsConfig ({e}); object count unknown")
            if self._v2_profile_declared():
                self._parse_error(note)
            else:
                self.model.parse_notes.append(note)
            return
        ae.objects = m.ObjectsConfig(objects_config_size=size,
                                     num_objects=num_objects,
                                     extension_bytes=size - 1)

    def _parse_mix_presentation(self, r: ByteReader, hdr: m.OBUHeader) -> None:
        from .layouts import (SOUND_SYSTEM, LAYOUT_TYPE_SS, LAYOUT_TYPE_BINAURAL)
        mp_id = r.uleb128()
        count_label = r.uleb128()
        language_labels = [r.cstring() for _ in range(count_label)]
        annotations = [r.cstring() for _ in range(count_label)]
        num_sub_mixes = r.uleb128()
        sub_mixes: list[m.SubMix] = []
        for _ in range(num_sub_mixes):
            num_ae = r.uleb128()
            ae_ids: list[int] = []
            rendering_configs: list[m.RenderingConfig] = []
            for _j in range(num_ae):
                ae_id = r.uleb128()
                ae_ids.append(ae_id)
                for _k in range(count_label):
                    r.cstring()               # localized element annotation
                rendering_configs.append(self._parse_rendering_config(r, mp_id, ae_id))
                # element_mix_config: MixGainParamDefinition
                self._parse_param_definition(r, None, mix_gain=True)
            # output_mix_config: MixGainParamDefinition
            self._parse_param_definition(r, None, mix_gain=True)
            num_layouts = r.uleb128()
            layouts: list[m.LoudnessLayout] = []
            for _k in range(num_layouts):
                lb = r.u8()
                layout_type = (lb >> 6) & 0x3
                sound_system = None
                label = "?"
                if layout_type == LAYOUT_TYPE_SS:
                    sound_system = (lb >> 2) & 0xF
                    label = SOUND_SYSTEM.get(sound_system, f"SS{sound_system}")
                elif layout_type == LAYOUT_TYPE_BINAURAL:
                    label = "Binaural"
                else:
                    label = f"reserved-layout-{layout_type}"
                ll = self._parse_loudness_info(r, layout_type, sound_system, label)
                layouts.append(ll)
            sub_mixes.append(m.SubMix(ae_ids, num_layouts, layouts, rendering_configs))
        mp = m.MixPresentation(
            mix_presentation_id=mp_id, count_label=count_label,
            language_labels=language_labels, annotations=annotations,
            sub_mixes=sub_mixes, header=hdr,
            friendly_annotations_present=any(a for a in annotations),
        )
        # Kept before the optional tail is read: a malformed tail is a parse
        # error (S-108), not a missing Mix Presentation (S-105).
        self.model.mix_presentations.append(mp)
        if hdr.optional_fields_flag:
            # The optional fields follow MixPresentationTags, so the tags are
            # walked to reach them (the tags themselves are not modelled).
            for _ in range(r.u8()):           # num_tags
                r.cstring()                   # tag_name
                r.cstring()                   # tag_value
            # optional_fields_size is an envelope: two renderer bytes, then
            # optional_fields_remaining_bytes (reserved; skipped with the rest).
            size = r.uleb128()
            if size < 2:
                raise ParseError(f"optional_fields_size {size} cannot hold the two "
                                 "preferred-renderer bytes", r.abs_pos)
            fields = r.subreader(size)
            mp.optional_fields_size = size
            mp.preferred_loudspeaker_renderer = fields.u8()
            mp.preferred_binaural_renderer = fields.u8()

    def _v2_profile_declared(self) -> bool:
        """Whether the sequence declares a profile that IAMF v2.0.0 defines
        (3..5), as primary or additional: object-based elements and the
        v2.0.0 RenderingConfig() syntax exist in that version only."""
        sh = self.model.sequence_header
        return sh is not None and (sh.primary_profile in _OBJECT_PROFILES
                                   or sh.additional_profile in _OBJECT_PROFILES)

    def _parse_rendering_config(self, r: ByteReader, mp_id: int,
                                ae_id: int) -> m.RenderingConfig:
        """RenderingConfig() (IAMF v2.0.0, v2:1457-1491).

        rendering_config_extension_size is an envelope, and v2.0.0 puts
        num_parameters, the parameter definitions and the element gain offset
        inside it (v2:1543, v2:1585). Bytes past them are reserved and skipped
        with the envelope, so whatever the envelope holds, the fields after it
        are found where they were before.

        An empty envelope is the v1.1.0 form and reads as before: no
        parameters. v2.0.0 streams use it too when they have nothing to put
        there.

        Envelope bytes that do not follow the v2.0.0 syntax leave the config
        in the model with extension_read False. Whether that is an error
        depends on what the sequence declares, as for ObjectsConfig(). Before
        v2.0.0 these bytes were reserved and the three bits now read as
        element_gain_offset_flag and binaural_filter_profile were reserved
        too, so a stream that declares no profile from 3..5 may carry
        anything there: a note. When either profile is one that v2.0.0
        defines, the syntax is required and the failure is a genuine parse
        error (S-108).
        """
        mode, gain_flag, filter_profile, reserved = split_bits(r.u8(), 2, 1, 2, 3)
        size = r.uleb128()
        envelope = r.subreader(size)
        rc = m.RenderingConfig(
            headphones_rendering_mode=mode, element_gain_offset_flag=bool(gain_flag),
            binaural_filter_profile=filter_profile, reserved=reserved,
            rendering_config_extension_size=size)
        if size == 0 and not gain_flag:
            return rc
        try:
            if size == 0:
                raise ParseError("element_gain_offset_flag is set but "
                                 "rendering_config_extension_size 0 leaves no room "
                                 "for an ElementGainOffsetConfig", envelope.abs_pos)
            num_parameters = envelope.uleb128()
            positions: list[m.PositionParamDefinition] = []
            others: list[int] = []
            for _ in range(num_parameters):
                ptype = envelope.uleb128()
                n_objects = m.POSITION_PARAM_OBJECTS.get(ptype)
                if n_objects is None:
                    # Every other type, defined or not, is param_definition_size
                    # and that many bytes (v2:1480-1483).
                    envelope.read(envelope.uleb128())
                    others.append(ptype)
                    continue
                pd = self._parse_param_definition(envelope, ptype, mix_gain=False)
                positions.append(m.PositionParamDefinition(
                    ptype, pd, [self._read_position(envelope, ptype)
                                for _ in range(n_objects)]))
            gain = self._parse_element_gain_offset(envelope) if gain_flag else None
        except ParseError as e:
            rc.extension_read = False
            note = (f"mix_presentation {mp_id} / audio_element {ae_id}: "
                    "rendering_config extension does not follow the IAMF v2.0.0 "
                    f"syntax ({e}); its parameters are not read")
            if self._v2_profile_declared():
                self._parse_error(note)
            else:
                self.model.parse_notes.append(note)
            return rc
        rc.num_parameters = num_parameters
        rc.position_definitions = positions
        rc.other_param_definition_types = others
        rc.element_gain_offset = gain
        rc.extension_bytes = envelope.remaining()
        return rc

    @staticmethod
    def _read_position(r: ByteReader, ptype: int) -> tuple[int, int, int]:
        """The default position of one object, as coded."""
        if ptype in m.POLAR_PARAM_TYPES:
            # signed 9-bit azimuth, signed 8-bit elevation, unsigned 7-bit
            # distance, packed MSB-first into three bytes (v2:1679-1681)
            b = r.read(3)
            v = (b[0] << 16) | (b[1] << 8) | b[2]
            azimuth, elevation, distance = v >> 15, (v >> 7) & 0xFF, v & 0x7F
            return (azimuth - 0x200 if azimuth & 0x100 else azimuth,
                    elevation - 0x100 if elevation & 0x80 else elevation, distance)
        if ptype in (m.PARAM_CART8, m.PARAM_DUAL_CART8):
            return (r.s8(), r.s8(), r.s8())           # v2:1772-1774
        return (r.s16(), r.s16(), r.s16())            # v2:1804-1806

    @staticmethod
    def _parse_element_gain_offset(r: ByteReader) -> m.ElementGainOffsetConfig:
        """ElementGainOffsetConfig() (v2:1593-1605)."""
        cfg = m.ElementGainOffsetConfig(element_gain_offset_type=r.u8())
        if cfg.element_gain_offset_type == m.GAIN_OFFSET_VALUE:
            cfg.element_gain_offset = r.s16()
        elif cfg.element_gain_offset_type == m.GAIN_OFFSET_RANGE:
            cfg.default_element_gain_offset = r.s16()
            cfg.min_element_gain_offset = r.s16()
            cfg.max_element_gain_offset = r.s16()
        else:                                         # reserved type: size + bytes
            cfg.extension_bytes = r.uleb128()
            r.read(cfg.extension_bytes)
        return cfg

    def _parse_loudness_info(self, r: ByteReader, layout_type: int,
                             sound_system: int | None,
                             label: str) -> m.LoudnessLayout:
        info_type = r.u8()
        integrated_raw = r.s16()
        digital_raw = r.s16()
        ll = m.LoudnessLayout(
            layout_type=layout_type, sound_system=sound_system, label=label,
            info_type=info_type,
            integrated_loudness=integrated_raw / 256.0,
            digital_peak=digital_raw / 256.0,
            integrated_raw=integrated_raw, digital_peak_raw=digital_raw,
        )
        if info_type & 0x1:            # TRUE_PEAK
            ll.true_peak = r.s16() / 256.0
        if info_type & 0x2:            # ANCHORED_LOUDNESS
            n = r.u8()
            for _ in range(n):
                r.u8()                 # anchor_element
                r.s16()                # anchored_loudness
        if info_type & 0xFC:           # info_type_extension
            size = r.uleb128()
            r.read(size)
        return ll

    def _parse_parameter_block(self, r: ByteReader, hdr: m.OBUHeader) -> None:
        pid = r.uleb128()
        self.model.parameter_block_ids.append(pid)

    def _parse_audio_frame(self, r: ByteReader, hdr: m.OBUHeader, *,
                           first_temporal: bool) -> None:
        if hdr.obu_type == m.OBU_AUDIO_FRAME:
            sub_id = r.uleb128()
        else:
            sub_id = hdr.obu_type - m.OBU_AUDIO_FRAME_ID0
        self.model.audio_frames.append(m.AudioFrameRef(
            substream_id=sub_id, obu_type=hdr.obu_type, file_offset=hdr.file_offset,
            payload_len=hdr.payload_len, first_temporal=first_temporal,
            trim_start=hdr.num_samples_to_trim_at_start,
            trim_end=hdr.num_samples_to_trim_at_end,
            frame_bytes=r.remaining(),
        ))


def parse_bytes(data: bytes, *, source: str = "", container: str = "raw") -> m.IAMFModel:
    return IAMFParser(data, source=source, container=container).parse()
