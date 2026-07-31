"""IAMF loudspeaker-layout and sound-system tables (clean-room, from the spec).

These tables are the ground truth the L2 channel-semantics checks validate
against. Anchor points confirmed byte-for-byte against the WP1 structural
evidence (structural_diff.json): Stereo=lsl 1 (1 substream / 1 coupled),
5.1=lsl 2 (4 / 2), 7.1.4=lsl 7 (7 / 5). The remaining rows follow the
IAMF v1.1.0 scalable_channel_layout_config definition (coupled pairs first,
C/LFE uncoupled last).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelLayout:
    name: str
    channels: int
    # Expected counts for the FULL (top) layer of a non-scalable element:
    expected_substreams: int
    expected_coupled: int


# loudspeaker_layout (4-bit) -> layout.  The (substreams, coupled) pair is what
# a single-layer element MUST declare; scalable multi-layer elements are the
# incremental deltas between layers and are checked separately.
LOUDSPEAKER_LAYOUT: dict[int, ChannelLayout] = {
    0: ChannelLayout("Mono", 1, 1, 0),
    1: ChannelLayout("Stereo", 2, 1, 1),
    2: ChannelLayout("5.1", 6, 4, 2),
    3: ChannelLayout("5.1.2", 8, 5, 3),
    4: ChannelLayout("5.1.4", 10, 6, 4),
    5: ChannelLayout("7.1", 8, 5, 3),
    6: ChannelLayout("7.1.2", 10, 6, 4),
    7: ChannelLayout("7.1.4", 12, 7, 5),
    8: ChannelLayout("3.1.2", 6, 4, 2),
    9: ChannelLayout("Binaural", 2, 1, 1),
    # 10..14 reserved
    15: ChannelLayout("Expanded", -1, -1, -1),  # use expanded_loudspeaker_layout
}

RESERVED_LOUDSPEAKER_LAYOUTS = {10, 11, 12, 13, 14}

# expanded_loudspeaker_layout (8-bit, only when loudspeaker_layout == 15).
# Base-Enhanced profile feature (IAMF v1.1.0). Names per spec; counts are
# informational for Phase 1 (checked leniently).
EXPANDED_LOUDSPEAKER_LAYOUT: dict[int, str] = {
    0: "LFE",
    1: "Stereo-S",
    2: "Stereo-SS",
    3: "Stereo-RS",
    4: "Stereo-TF",
    5: "Stereo-TB",
    6: "Top-4ch",
    7: "3.0.ch",
    8: "9.1.6",
    9: "Stereo-F",
    10: "Stereo-Si",
    11: "Stereo-TpSi",
    12: "Top-6ch",
}

# Layout.sound_system (4-bit, LOUDSPEAKERS_SS_CONVENTION) used in mix
# presentation loudness layouts. Values 0..9 map to ITU-R BS.2051 sound systems
# A..J in order; 10..11 are IAMF extensions.
#   Provenance: ss 0 (Stereo) and ss 1 (5.1) are byte-verified against the WP1
#   real samples (stereo files + the 5.1 YouTube MP4 loudness layouts). The rest
#   are the stable BS.2051 A..J letters + IAMF extension set; labels for E/F/G
#   use the ITU config string (no clean consumer name) to avoid asserting a
#   wrong friendly label. Recheck the exact IAMF ext values (10/11) on a spec bump.
SOUND_SYSTEM: dict[int, str] = {
    0: "Stereo",       # A  0+2+0   [verified]
    1: "5.1",          # B  0+5+0   [verified]
    2: "5.1.2",        # C  2+5+0
    3: "5.1.4",        # D  4+5+0
    4: "E(4+5+1)",     # E  4+5+1
    5: "F(3+7+0)",     # F  3+7+0
    6: "G(4+9+0)",     # G  4+9+0
    7: "22.2",         # H  9+10+3
    8: "7.1",          # I  0+7+0
    9: "7.1.4",        # J  4+7+0
    10: "7.1.2",       # IAMF ext  2+7+0
    11: "3.1.2",       # IAMF ext  2+3+0
}

# layout_type (2-bit)
LAYOUT_TYPE_RESERVED_0 = 0
LAYOUT_TYPE_RESERVED_1 = 1
LAYOUT_TYPE_SS = 2      # LOUDSPEAKERS_SS_CONVENTION
LAYOUT_TYPE_BINAURAL = 3



def order_from_ambisonics_channels(n: int) -> int | None:
    """Inverse of (N+1)^2; None if n is not a perfect ambisonic channel count."""
    if n <= 0:
        return None
    root = int(round(n ** 0.5))
    return root - 1 if root * root == n else None
