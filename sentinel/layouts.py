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
# a single-layer element MUST declare, and what the first layer of a scalable
# element declares; the layers above it declare only what they add to the
# layer below (channel_group_counts, further down).
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

# X.Y.Z of each loudspeaker_layout a scalable element may layer: surround, LFE
# and height channel counts, as the Channel Layout Generation Rule reads a
# layout (v2:1168, v1.1:1110, err:1043; the prefixes are source lines of
# index.bs in IAMF v2.0.0 at 4d2c6da, in v1.1.0 and in v1.0.0-errata).
# Binaural (9) and the expanded layouts (15) have no row: with either,
# num_layers is 1 (v2:964, v2:1138).
LAYOUT_XYZ: dict[int, tuple[int, int, int]] = {
    0: (1, 0, 0),      # Mono
    1: (2, 0, 0),      # Stereo
    2: (5, 1, 0),      # 5.1
    3: (5, 1, 2),      # 5.1.2
    4: (5, 1, 4),      # 5.1.4
    5: (7, 1, 0),      # 7.1
    6: (7, 1, 2),      # 7.1.2
    7: (7, 1, 4),      # 7.1.4
    8: (3, 1, 2),      # 3.1.2
}

# expanded_loudspeaker_layout (8-bit, only when loudspeaker_layout == 15).
# Base-Enhanced profile feature (IAMF v1.1.0). Names per spec; counts are
# informational for Phase 1 (checked leniently). 13..19 are defined by IAMF
# v2.0.0 and reserved in v1.1.0; 20..255 are reserved in both.
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
    13: "10.2.9.3",
    14: "LFE-Pair",
    15: "Bottom-3ch",
    16: "7.1.5.4",
    17: "Bottom-4ch",
    18: "Top-1ch",
    19: "Top-5ch",
}

# Channels per expanded layout. The spec's table has no channel-count column;
# each figure is the number of entries in that row's "Loudspeaker Location
# Ordering" (IAMF v2.0.0 source line cited per row; the three long orderings
# are spelled out at v2:1130, v2:1132 and v2:1134).
EXPANDED_LAYOUT_CHANNELS: dict[int, int] = {
    0: 1,      # LFE                                   v2:1066
    1: 2,      # Stereo-S      Ls/Rs                   v2:1069
    2: 2,      # Stereo-SS     Lss/Rss                 v2:1072
    3: 2,      # Stereo-RS     Lrs/Rrs                 v2:1075
    4: 2,      # Stereo-TF     Ltf/Rtf                 v2:1078
    5: 2,      # Stereo-TB     Ltb/Rtb                 v2:1081
    6: 4,      # Top-4ch       Ltf/Rtf/Ltb/Rtb         v2:1084
    7: 3,      # 3.0ch         L/C/R                   v2:1087
    8: 16,     # 9.1.6ch       16 locations            v2:1090, v2:1130
    9: 2,      # Stereo-F      FL/FR                   v2:1093
    10: 2,     # Stereo-Si     SiL/SiR                 v2:1096
    11: 2,     # Stereo-TpSi   TpSiL/TpSiR             v2:1099
    12: 6,     # Top-6ch       6 locations             v2:1102
    13: 24,    # 10.2.9.3ch    24 locations            v2:1105, v2:1132
    14: 2,     # LFE-Pair      LFE1/LFE2               v2:1108
    15: 3,     # Bottom-3ch    BtFL/BtFC/BtFR          v2:1111
    16: 17,    # 7.1.5.4ch     17 locations            v2:1114, v2:1134
    17: 4,     # Bottom-4ch    BtFL/BtFR/BtBL/BtBR     v2:1117
    18: 1,     # Top-1ch       TpC                     v2:1120
    19: 5,     # Top-5ch       Ltf/Rtf/TpC/Ltb/Rtb     v2:1123
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


def channel_group_counts(below: int | None, lsl: int) -> tuple[int, int] | None:
    """(substream_count, coupled_substream_count) of the Channel Group that a
    layer of loudspeaker_layout ``lsl`` (0..9) carries.

    ``below`` is the loudspeaker_layout of the layer under it, None for the
    first layer. The first layer's group is its whole layout: the table row.
    A layer above it carries only the channels its layout adds (Channel Group
    Format, v2:1180-1193; v1.1:1120-1133 and err:1053-1066 say the same), each
    pair of coupled stereo channels as one substream and every other channel
    as one substream of its own (v2:1037-1039):

        surround  2 in (X below, X]   L2            1 substream, not coupled
                  3                   Centre        1 substream, not coupled
                  5                   L5/R5         1 coupled substream
                  7                   Lss7/Rss7     1 coupled substream
        LFE       Y below < Y         LFE           1 substream, not coupled
        height    Z below < Z         top pairs     (Z - Z below) / 2 coupled

    L2 alone is not a pair, which is why a Mono first layer leaves the whole
    element one substream more and one coupled substream fewer than the same
    top layout coded as a single layer. From any other first layer the layers
    sum to the top layout's table row.

    None when the specification defines no such group: the two layouts do not
    follow the Channel Layout Generation Rule (v2:1167-1171: X, Y and Z never
    decrease and are not all equal), or one of them is Binaural or an expanded
    layout, which a scalable element does not contain.
    """
    if below is None:
        cl = LOUDSPEAKER_LAYOUT[lsl]
        return cl.expected_substreams, cl.expected_coupled
    if below not in LAYOUT_XYZ or lsl not in LAYOUT_XYZ:
        return None
    (px, py, pz), (x, y, z) = LAYOUT_XYZ[below], LAYOUT_XYZ[lsl]
    if px > x or py > y or pz > z or (px, py, pz) == (x, y, z):
        return None
    coupled = (px < 5 <= x) + (px < 7 <= x) + (z - pz) // 2
    single = (px < 2 <= x) + (px < 3 <= x) + (y - py)
    return coupled + single, coupled
