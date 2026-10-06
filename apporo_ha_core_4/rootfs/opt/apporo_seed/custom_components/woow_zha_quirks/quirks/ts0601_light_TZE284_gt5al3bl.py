"""ZHA Quirk (v11) for Gledopto GL-SPI-206P (_TZE284_gt5al3bl / TS0601)

Tuya Zigbee SPI Addressable LED Strip Controller (幻彩燈控制器).
Controls RGBCW addressable LED strips (WS2801, WS2811, SK6812, etc.).

WLED-style light entity: exposes a single HA `light.*` entity with
color wheel (HS), color temperature slider, brightness slider, and
scene effects — instead of individual number/select entities.

v11 Scenes as light EFFECTS (not a select):
  - The 44 scenes are now exposed on the light entity's native "Effect"
    button (light.effect_list / turn_on(effect=...)) instead of a separate
    scene `select`. ZHA's light platform hard-codes effect_list to
    off/colorloop with no quirk hook, so this is done by a guarded runtime
    monkey-patch of the zha Light class in ../light_effects.py, which calls
    TuyaSPILightMCUCluster.play_scene(). SCENE_DATA/SCENE_NAMES/ScenePreset
    are kept (imported by that patch); the DP51 select entity was removed.

v10 Full 44-scene library:
  - Expanded the scene `select` from 16 to the device's full 44 built-in
    scenes (the SmartLife app's landscape/Life/festival/Feeling tabs).
    All 44 raw DP51 payloads were captured live from the app via Tuya-cloud
    DP51 read-back (docs/woow-product/18-led-strip-scenes.md); the previous
    16 are a subset and are byte-identical. ScenePreset/SCENE_DATA now hold
    all 44 (select index 0..43 = app display order); the scene-send path
    (tuya_mcu_command) and builder are unchanged (already index-generic).

v9 Correct Scene Data Format:
  - Replaced SCENE_DATA payloads with correct format from Zigbee2MQTT
    GL-SPI-206P converter (zigbee-herdsman-converters/gledopto.ts).
    Old data used 0x00 version byte with HSV+white 10-byte color blocks
    (from standard Tuya light scenes). Correct format uses 0x01 version
    byte with built-in scene IDs and 3-byte color nodes — the format
    the Gledopto SPI MCU firmware actually understands.
  - Removed unused _send_scene_sequence_async / _send_scene_sequence.

v8 Scene Fix (endpoint attribute name):
  - Fixed `self.endpoint.color` → `self.endpoint.light_color` in all
    _dp_2_attr_update handlers (DP2, DP4, DP61). The ZCL Color cluster
    registers as `ep_attribute = "light_color"` on the endpoint, not
    "color". The KeyError was caught by handle_cluster_request's broad
    `except AttributeError` and silently dropped, preventing scene mode
    from updating OnOff/Level/Color state — which caused the HA entity
    to not reflect the device's actual scene-playing state.

v7 Incoming DP Routing Fix:
  - Override handle_get_data / handle_set_data_response so that incoming
    DP reports (command 0x01 and 0x02) for DPs 1/2/3/4/51/61 are routed
    through our custom _dp_2_attr_update method instead of being dropped
    with "No datapoint handler" warnings.
  - Root cause: the parent TuyaMCUCluster.handle_get_data only looks in
    data_point_handlers dict, which only has builder-registered DPs. Our
    light DPs (1/2/3/4/61) are handled by custom ZCL clusters and were
    never reached.

v6 Scene Fix:
  - Scene command now sends DP1=on BEFORE DP2=scene + DP51=data so the
    LED strip stays powered on during scene playback.
  - DP2 incoming handler now properly handles scene mode (mode=2) to
    keep OnOff cluster state as "on" and brightness at full during
    scene playback, preventing the light entity from showing 0%.
  - Removed unreachable super()._dp_2_attr_update() call in DP2 handler
    that caused "No datapoint handler" log warnings.

v5 Performance Fix:
  All ZCL cluster command() methods send Tuya DPs **directly** to the
  MCU cluster via fire-and-forget `create_catching_task`, bypassing the
  command bus entirely.  A deferred-batch queue in the MCU cluster
  collects DPs queued within a 15ms window and flushes them in a single
  Zigbee frame.  This eliminates the "command pileup" problem where
  the ZHA light platform's sequential await pattern would generate
  multiple separate Zigbee frames per UI interaction.

Architecture:
  - TuyaSPIOnOff       — ZCL OnOff cluster → queues DP1 to MCU batch
  - TuyaSPILevelControl — ZCL LevelControl → queues DP3 (+ DP1) to MCU batch
  - TuyaSPIColorControl — ZCL Color → queues DP2+DP61 or DP2+DP4, flushes batch
  - TuyaSPILightMCUCluster — TuyaMCU + deferred DP batch queue
  - CONFIG entities for pixel_count, chip_type, color_order, DND

DP Map:
  DP  1   : Power on/off             (bool)
  DP  2   : Work mode                (enum: 0=white, 1=colour, 2=scene, 3=music)
  DP  3   : Brightness               (value: 10-1000)
  DP  4   : Color temperature        (value: 0-1000, 0=warm, 1000=cold)
  DP  51  : Scene mode data          (raw bytes)
  DP  53  : Pixel count setting      (value: 10-1000)
  DP  61  : Color data               (raw 11-byte SmearFormater HSV payload)
  DP  101 : Color order              (enum)
  DP  102 : Chip type                (enum)
  DP  103 : Do not disturb           (bool)

DP 61 SmearFormater Protocol (11 bytes):
  Byte 0:     version       (0x00)
  Byte 1:     dimmerMode    (0x00=white, 0x01=colour)
  Byte 2:     effect        (0x00=none)
  Byte 3:     ledNumber     (segments, e.g. 0x14=20)
  Byte 4:     smearMode     (0x00=all)
  Bytes 5-6:  hue           (0-360, big-endian uint16)
  Bytes 7-8:  saturation    (0-1000, big-endian uint16)
  Bytes 9-10: value         (0-1000, big-endian uint16)
"""

from __future__ import annotations

import asyncio
import colorsys
import struct
from typing import Any

from zigpy.profiles import zha
from zigpy.quirks.v2.homeassistant import EntityType
import zigpy.types as t
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.clusters.lighting import Color

from zhaquirks.tuya import (
    NoManufacturerCluster,
    TuyaCommand,
    TuyaData,
    TuyaDatapointData,
    TuyaDPType,
    TuyaLocalCluster,
)
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import (
    TuyaClusterData,
    TuyaMCUCluster,
)


# ────────────────────────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────────────────────────

class WorkMode(t.enum8):
    White = 0x00
    Colour = 0x01
    Scene = 0x02
    Music = 0x03


class ChipType(t.enum8):
    WS2801 = 0x00
    LPD6803 = 0x01
    LPD8803 = 0x02
    WS2811 = 0x03
    TM1814B = 0x04
    TM1934A = 0x05
    SK6812 = 0x06
    SK9822 = 0x07
    UCS8904B = 0x08
    WS2805 = 0x09


class ColorOrder(t.enum8):
    RGB = 0x00
    RBG = 0x01
    GRB = 0x02
    GBR = 0x03
    BRG = 0x04
    BGR = 0x05
    RGBW = 0x09
    RBGW = 0x0A
    GRBW = 0x0B
    GBRW = 0x0C
    BRGW = 0x0D
    BGRW = 0x0E
    WRGB = 0x0F
    WRBG = 0x10
    WGRB = 0x11


class ScenePreset(t.enum8):
    """All 44 scenes from the SmartLife app, in the app's display order.

    The enum *value* is the select index (0..43), used as the key into
    SCENE_DATA; the actual firmware scene_id is byte[1] of each payload.
    Captured live 2026-07-07 (see docs/woow-product/18-led-strip-scenes.md).
    """

    # ── "landscape" tab (app page 1) ──
    Iceland_Blue = 0
    Glacier_Express = 1
    Sea_of_Clouds = 2
    Fireworks_at_Sea = 3
    Hut_in_the_Snow = 4
    Firefly_Night = 5
    Northland = 6
    Grassland = 7
    Northern_Lights = 8
    Late_Autumn = 9
    Dream_Meteor = 10
    Early_Spring = 11
    Spring_Outing = 12
    Night_Service = 13
    Wind_Chime = 14
    City_Lights = 15
    Color_Marbles = 16
    Summer_Train = 17
    Christmas_Eve = 18
    Dream_Sea = 19
    # ── "Life" tab (app page 2) ──
    Game = 20
    Holiday = 21
    Work = 22
    Party = 23
    Trend = 24
    Sports = 25
    Meditation = 26
    Dating = 27
    # ── "festival" tab (app page 3) ──
    Christmas = 28
    Valentines_Day = 29
    Halloween = 30
    Thanksgiving_Day = 31
    Forest_Day = 32
    Mothers_Day = 33
    Fathers_Day = 34
    Football_Day = 35
    # ── "Feeling" tab (app page 4) ──
    Summer_Idyll = 36
    Dream_of_the_Sea = 37
    Love_and_Dream = 38
    Spring_Fishing = 39
    Neon_World = 40
    Dreamland = 41
    Summer_Wind = 42
    Planet_Journey = 43


# ────────────────────────────────────────────────────────────────
# Scene data payloads — the device's FULL 44-scene "dreamlight" library,
# captured live from the SmartLife app via Tuya-cloud DP51 read-back
# (2026-07-07; see docs/woow-product/18-led-strip-scenes.md). Each value is
# the exact raw DP51 blob the app sends; keyed by the ScenePreset select index.
# Format: version(0x01) + scene_id(1) + effect_type(1) + speed(1) + gap(1)
#         + per-color-node: hue_flags(1) + hue(1) + brightness(1)
# Spaced hex is copied verbatim from the capture and decoded to bytes below.
# ────────────────────────────────────────────────────────────────

_SCENE_HEX = {
    # ── "landscape" tab ──
    0:  "01 15 0a 52 52 e0 00 00 64 00 c1 61 00 b4 30 00 b5 52 00 c4 63",  # Iceland Blue
    1:  "01 16 0a 64 64 60 00 00 64 00 92 5f 00 c6 60",                    # Glacier Express
    2:  "01 17 03 5e 5e 60 00 00 64 00 38 2f 00 1e 5c 00 d5 45 01 1a 64",  # Sea of Clouds
    3:  "01 18 02 64 64 e0 00 00 64 00 b2 39 01 0a 64 01 2d 64 01 3f 64",  # Fireworks at Sea
    4:  "01 19 0a 54 54 60 00 00 64 00 b1 2c 00 c0 64",                    # Hut in the Snow
    5:  "01 1a 03 4b 4b e0 00 00 64 00 e0 39 01 09 53",                    # Firefly Night
    6:  "01 1b 03 5f 5f 60 00 00 64 00 ae 39 00 c4 5d 00 f9 64",           # Northland
    7:  "01 1c 0a 5a 5a e0 00 00 52 00 9d 64 00 8e 64",                    # Grassland
    8:  "01 1d 03 52 52 e0 00 00 64 00 ae 64 00 a6 64 00 c1 64 00 cc 64",  # Northern Lights
    9:  "01 1e 0a 52 52 e0 00 00 64 00 19 64 00 22 5e 00 2c 5b 00 14 64 00 0c 64",  # Late Autumn
    10: "01 47 05 4d 4d 00 00 00 64 01 03 45 00 c1 43",                    # Dream Meteor
    11: "01 48 06 32 32 00 00 00 64 01 4e 41 00 1f 49",                    # Early Spring
    12: "01 49 07 0e 0e 00 00 00 64 00 da 37 01 52 41 00 5c 37",           # Spring Outing
    13: "01 4a 08 32 32 00 00 00 64 00 f7 50 00 29 4f 01 0d 38 00 a3 27",  # Night Service
    14: "01 4b 09 32 32 00 00 00 64 01 03 45 00 41 3a 00 25 4b 00 5e 42",  # Wind Chime
    15: "01 4c 0c 32 32 00 00 00 64 00 d8 4d 00 c1 43 01 03 45 00 5c 37",  # City Lights
    16: "01 4d 0d 32 32 00 00 00 64 00 28 64 00 5e 42 00 c1 64 00 ff 50",  # Color Marbles
    17: "01 4e 0e 32 32 00 00 00 64 00 3e 5f 00 be 5c",                    # Summer Train
    18: "01 4f 0f 19 19 00 00 00 64 00 bc 64 00 2d 4e 00 00 64 00 64 3c",  # Christmas Eve
    19: "01 50 10 32 32 00 00 00 64 00 e6 47 00 64 3c 01 19 4d 00 b8 39",  # Dream Sea
    # ── "Life" tab ──
    20: "01 1f 02 5f 5f 60 00 00 64 01 10 64 00 d2 64 00 ad 64 00 8b 64",  # Game
    21: "01 20 0a 55 55 60 00 00 64 00 c2 58 01 3e 33 00 ff 46 01 1d 64",  # Holiday
    22: "01 21 03 3c 3c 60 00 00 64 00 bf 18 01 04 17",                    # Work
    23: "01 22 04 64 64 60 00 00 64 00 d7 5c 00 bc 53 00 37 1e 00 2c 3f 01 61 3f",  # Party
    24: "01 23 02 64 64 60 00 00 64 01 08 4b 00 b1 2f 00 cd 57",           # Trend
    25: "01 24 0a 4b 4b 60 00 00 64 00 bc 26 00 d6 55 01 18 64 00 f9 4d",  # Sports
    26: "01 25 03 43 43 60 00 00 64 00 b7 35 00 9b 54 00 cd 61",           # Meditation
    27: "01 26 01 59 59 e0 00 00 64 01 19 47 01 49 3d 00 cd 61 00 26 64",  # Dating
    # ── "festival" tab ──
    28: "01 29 02 61 61 e0 00 00 64 00 0b 64 00 d9 64 00 2b 64 00 91 64 00 b9 64",  # Christmas
    29: "01 2a 01 64 64 60 00 00 64 01 15 64 01 05 64 01 45 64 01 2f 64",  # Valentine's Day
    30: "01 2b 03 5a 5a e0 00 00 64 00 00 57 01 16 64 00 da 64 00 b3 64 00 95 64",  # Halloween
    31: "01 2c 0a 48 48 60 00 00 64 00 3d 64 01 0c 5b 00 ba 49 00 17 61",  # Thanksgiving Day
    32: "01 2d 02 59 59 60 00 00 64 00 9c 63 00 bc 62 00 7b 60",           # Forest Day
    33: "01 2e 03 5a 5a 60 00 00 64 01 3e 36 01 0c 56 01 1f 23",           # Mother's Day
    34: "01 2f 02 64 64 e0 00 00 64 00 dc 42 00 b6 4a 00 e1 4d",           # Father's Day
    35: "01 30 02 5e 5e 60 00 00 64 00 00 64 00 78 64 00 bb 64",           # Football Day
    # ── "Feeling" tab ──
    36: "01 33 03 52 52 60 00 00 64 00 88 50 00 d2 39 00 fb 27",           # Summer Idyll
    37: "01 34 03 5d 5d 60 00 00 64 00 f7 36 01 35 2b 00 c6 34 00 91 29",  # Dream of the Sea
    38: "01 35 03 52 52 60 00 00 4d 01 12 62 01 30 5d",                    # Love and Dream
    39: "01 36 02 49 49 60 00 00 64 00 66 3c 00 3c 49 00 1e 64",           # Spring Fishing
    40: "01 37 0a 5a 5a 60 00 00 64 00 33 58 00 18 64 01 00 45 00 e3 5e 00 ac 30",  # Neon World
    41: "01 38 02 57 57 e0 00 00 64 01 0c 64 01 1a 41 01 47 59 00 15 64 00 3c 38",  # Dreamland
    42: "01 39 03 48 48 e0 00 00 64 00 59 64 00 b3 47",                    # Summer Wind
    43: "01 3a 02 5d 5d e0 00 00 4d 00 b4 5e 01 1c 64 00 e8 49 00 c6 5f",  # Planet Journey
}

SCENE_DATA = {k: bytes.fromhex(h.replace(" ", "")) for k, h in _SCENE_HEX.items()}

SCENE_NAMES = [e.name.replace("_", " ") for e in ScenePreset]


# ────────────────────────────────────────────────────────────────
# Color conversion helpers
# ────────────────────────────────────────────────────────────────

def _xy_to_hs(x: float, y: float) -> tuple[int, int]:
    """Convert CIE xy (0.0-1.0) to Tuya HSV (hue 0-360, sat 0-1000)."""
    if y < 0.001:
        return (0, 0)
    Y = 1.0
    X = (Y / y) * x
    Z = (Y / y) * (1.0 - x - y)
    r = X * 3.2406 - Y * 1.5372 - Z * 0.4986
    g = -X * 0.9689 + Y * 1.8758 + Z * 0.0415
    b = X * 0.0557 - Y * 0.2040 + Z * 1.0570
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return (round(h * 360) % 360, round(s * 1000))


def _hs_to_xy(hue: int, sat: int) -> tuple[int, int]:
    """Convert Tuya HSV (hue 0-360, sat 0-1000) to CIE xy (0-65535)."""
    h = (hue % 360) / 360.0
    s = min(1000, max(0, sat)) / 1000.0
    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    X = r * 0.4124 + g * 0.3576 + b * 0.1805
    Y = r * 0.2126 + g * 0.7152 + b * 0.0722
    Z = r * 0.0193 + g * 0.1192 + b * 0.9505
    total = X + Y + Z
    if total < 0.001:
        cx, cy = 0.3127, 0.3290
    else:
        cx = X / total
        cy = Y / total
    return (round(cx * 65535), round(cy * 65535))


# ────────────────────────────────────────────────────────────────
# Custom ZCL OnOff Cluster — bridges DP1
# ────────────────────────────────────────────────────────────────

class TuyaSPIOnOff(OnOff, TuyaLocalCluster):
    """OnOff cluster bridging Tuya DP1.

    Queues DP1 to MCU batch queue for deferred sending.
    """

    class AttributeDefs(OnOff.AttributeDefs):
        pass

    class ServerCommandDefs(OnOff.ServerCommandDefs):
        pass

    def _get_mcu(self):
        """Get the MCU cluster."""
        return self.endpoint.tuya_manufacturer

    async def command(
        self,
        command_id: foundation.GeneralCommand | int | t.uint8_t,
        *args,
        manufacturer: int | t.uint16_t | None = None,
        expect_reply: bool = True,
        tsn: int | t.uint8_t | None = None,
        **kwargs: Any,
    ):
        """Route on/off commands directly to MCU batch queue."""
        if command_id in (0x0000, 0x0001):
            on_val = bool(command_id)
            mcu = self._get_mcu()
            mcu.queue_dp(TuyaDatapointData(1, TuyaData(t.Bool(on_val))))
            # Update local attribute immediately for responsive UI
            self._update_attribute(OnOff.AttributeDefs.on_off.id, on_val)
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)
        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(
            command_id=command_id,
            status=foundation.Status.UNSUP_CLUSTER_COMMAND,
        )


class TuyaSPIOnOffNM(NoManufacturerCluster, TuyaSPIOnOff):
    """OnOff cluster with no manufacturer ID."""


# ────────────────────────────────────────────────────────────────
# Custom ZCL LevelControl Cluster — bridges DP3
# ────────────────────────────────────────────────────────────────

class TuyaSPILevelControl(LevelControl, TuyaLocalCluster):
    """LevelControl cluster bridging Tuya DP3 (brightness 10-1000).

    Queues DP3 (and DP1 for on_off) to MCU batch queue.
    """

    class AttributeDefs(LevelControl.AttributeDefs):
        pass

    def _get_mcu(self):
        """Get the MCU cluster."""
        return self.endpoint.tuya_manufacturer

    async def command(
        self,
        command_id: foundation.GeneralCommand | int | t.uint8_t,
        *args,
        manufacturer: int | t.uint16_t | None = None,
        expect_reply: bool = True,
        tsn: int | t.uint8_t | None = None,
        **kwargs: Any,
    ):
        """Route level commands directly to MCU batch queue."""
        level = kwargs.get("level") or (args[0] if args else 0)

        # move_to_level (0x0000), move_to_level_with_on_off (0x0004)
        if command_id in (0x0000, 0x0004):
            mcu = self._get_mcu()

            # For move_to_level_with_on_off, also queue on/off
            if command_id == 0x0004:
                on_val = bool(level)
                mcu.queue_dp(TuyaDatapointData(1, TuyaData(t.Bool(on_val))))
                # Update OnOff attribute
                on_off_cluster = self.endpoint.on_off
                if on_off_cluster:
                    on_off_cluster._update_attribute(
                        OnOff.AttributeDefs.on_off.id, on_val
                    )
                if not on_val:
                    return foundation.GENERAL_COMMANDS[
                        foundation.GeneralCommand.Default_Response
                    ].schema(
                        command_id=command_id,
                        status=foundation.Status.SUCCESS,
                    )

            # Map ZCL level (1-254) to Tuya brightness (10-1000)
            tuya_brightness = max(10, min(1000, round(
                (level - 1) * 990 / 253 + 10
            )))
            mcu.queue_dp(
                TuyaDatapointData(3, TuyaData(t.uint16_t(tuya_brightness)))
            )
            # Update local level attribute immediately
            self._update_attribute(
                LevelControl.AttributeDefs.current_level.id, level
            )
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(
            command_id=command_id,
            status=foundation.Status.UNSUP_CLUSTER_COMMAND,
        )


# ────────────────────────────────────────────────────────────────
# Custom ZCL Color Cluster — bridges DP2/DP4/DP61/DP51
# ────────────────────────────────────────────────────────────────

class TuyaSPIColorControl(Color, TuyaLocalCluster):
    """Color cluster bridging Tuya DPs for color, temp, and scene effects.

    Queues color DPs to MCU batch queue AND immediately flushes the
    entire batch (including any pending on/off + brightness DPs).
    """

    _CAPABILITIES = 0x01 | 0x02 | 0x08 | 0x10

    class AttributeDefs(Color.AttributeDefs):
        pass

    def __init__(self, *args, **kwargs):
        """Initialize with color temp range and capabilities."""
        super().__init__(*args, **kwargs)
        self._update_attribute(
            Color.AttributeDefs.color_capabilities.id, self._CAPABILITIES
        )
        self._update_attribute(
            Color.AttributeDefs.color_temp_physical_min.id, 153
        )
        self._update_attribute(
            Color.AttributeDefs.color_temp_physical_max.id, 370
        )
        self._update_attribute(
            Color.AttributeDefs.color_mode.id, 2
        )

    def _get_mcu(self):
        """Get the MCU cluster."""
        return self.endpoint.tuya_manufacturer

    async def command(
        self,
        command_id: foundation.GeneralCommand | int | t.uint8_t,
        *args,
        manufacturer: int | t.uint16_t | None = None,
        expect_reply: bool = True,
        tsn: int | t.uint8_t | None = None,
        **kwargs: Any,
    ):
        """Route color commands to MCU and flush the batch."""
        mcu = self._get_mcu()

        # move_to_color (0x0007) — XY color
        if command_id == 0x0007:
            color_x = kwargs.get("color_x") or (args[0] if len(args) > 0 else 0)
            color_y = kwargs.get("color_y") or (args[1] if len(args) > 1 else 0)
            x_norm = color_x / 65535.0
            y_norm = color_y / 65535.0
            hue, sat = _xy_to_hs(x_norm, y_norm)

            mcu.queue_color_hs(hue, sat)
            # Update local XY attributes immediately
            self._update_attribute(Color.AttributeDefs.current_x.id, color_x)
            self._update_attribute(Color.AttributeDefs.current_y.id, color_y)
            self._update_attribute(Color.AttributeDefs.color_mode.id, 1)
            # Flush all pending DPs NOW (on/off + brightness + color in one frame)
            mcu.flush_batch()
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        # move_to_color_temperature (0x000A)
        if command_id == 0x000A:
            color_temp_mireds = kwargs.get("color_temp_mireds") or (
                args[0] if args else 370
            )
            color_temp_mireds = max(153, min(370, color_temp_mireds))

            mcu.queue_color_temp(color_temp_mireds)
            self._update_attribute(
                Color.AttributeDefs.color_temperature.id, color_temp_mireds
            )
            self._update_attribute(Color.AttributeDefs.color_mode.id, 2)
            # Flush all pending DPs NOW
            mcu.flush_batch()
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        # move_to_hue_and_saturation (0x0006)
        if command_id == 0x0006:
            hue = kwargs.get("hue") or (args[0] if len(args) > 0 else 0)
            saturation = kwargs.get("saturation") or (
                args[1] if len(args) > 1 else 0
            )
            tuya_hue = round(hue * 360 / 254)
            tuya_sat = round(saturation * 1000 / 254)

            mcu.queue_color_hs(tuya_hue, tuya_sat)
            xy = _hs_to_xy(tuya_hue, tuya_sat)
            self._update_attribute(Color.AttributeDefs.current_x.id, xy[0])
            self._update_attribute(Color.AttributeDefs.current_y.id, xy[1])
            self._update_attribute(Color.AttributeDefs.color_mode.id, 0)
            mcu.flush_batch()
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(
            command_id=command_id,
            status=foundation.Status.UNSUP_CLUSTER_COMMAND,
        )


# ────────────────────────────────────────────────────────────────
# TuyaMCU Cluster — DP parsing, routing, and deferred batch queue
# ────────────────────────────────────────────────────────────────

# Batch flush delay in seconds.  Short enough to feel instant,
# long enough for the ZHA light platform to queue all its commands
# (OnOff → Level → Color) before we flush.
_BATCH_FLUSH_DELAY = 0.015  # 15 ms


class TuyaSPILightMCUCluster(TuyaMCUCluster):
    """Extended TuyaMCU cluster with deferred DP batch queue.

    The ZHA light platform sends multiple sequential ZCL commands for a
    single UI action (e.g., move_to_level_with_on_off → move_to_color).
    Instead of sending each DP separately, we collect them in a queue
    and flush them all in a single Zigbee frame.

    Queue lifecycle:
      1. ZCL cluster calls queue_dp() → DP added to _pending_dps dict
      2. A 15ms timer starts (or resets) — auto-flush safety net
      3. Color cluster calls flush_batch() → sends all pending DPs NOW
      4. If no Color command comes (simple on/off), timer flushes after 15ms
    """

    _current_hue: int = 0
    _current_saturation: int = 1000
    _current_value: int = 1000
    _led_segments: int = 20

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Deferred DP batch: dict keyed by DP number to allow dedup
        self._pending_dps: dict[int, TuyaDatapointData] = {}
        self._flush_handle: asyncio.TimerHandle | None = None

    # ── Batch queue API ─────────────────────────────────────────

    def queue_dp(self, dpd: TuyaDatapointData) -> None:
        """Add a DP to the pending batch, replacing any existing DP with same id.

        Starts or resets the auto-flush timer.
        """
        self._pending_dps[dpd.dp] = dpd
        self._schedule_flush()

    def queue_color_hs(self, hue: int, sat: int) -> None:
        """Queue DP2=colour + DP61 SmearFormater for HS color."""
        self._current_hue = hue
        self._current_saturation = sat
        payload = struct.pack(
            ">BBBBBHHH",
            0x00,  # version
            0x01,  # dimmerMode = colour
            0x00,  # effect
            self._led_segments,
            0x00,  # smearMode = all
            self._current_hue,
            self._current_saturation,
            self._current_value,
        )
        self._pending_dps[2] = TuyaDatapointData(
            2, TuyaData(t.enum8(0x01))
        )
        self._pending_dps[61] = self._make_raw_dpd(61, payload)
        # Remove conflicting white-mode DPs if present
        self._pending_dps.pop(4, None)

    def queue_color_temp(self, mireds: int) -> None:
        """Queue DP2=white + DP4 for color temperature."""
        tuya_temp = round((370 - mireds) / (370 - 153) * 1000)
        tuya_temp = max(0, min(1000, tuya_temp))
        self._pending_dps[2] = TuyaDatapointData(
            2, TuyaData(t.enum8(0x00))
        )
        self._pending_dps[4] = TuyaDatapointData(
            4, TuyaData(t.uint16_t(tuya_temp))
        )
        # Remove conflicting colour-mode DPs if present
        self._pending_dps.pop(61, None)

    def flush_batch(self) -> None:
        """Send all pending DPs in one Zigbee frame immediately."""
        self._cancel_flush_timer()
        if not self._pending_dps:
            return
        dpds = list(self._pending_dps.values())
        self._pending_dps.clear()
        self._fire_dp_commands(dpds)

    def _schedule_flush(self) -> None:
        """Start or reset the auto-flush timer."""
        self._cancel_flush_timer()
        try:
            loop = asyncio.get_running_loop()
            self._flush_handle = loop.call_later(
                _BATCH_FLUSH_DELAY, self.flush_batch
            )
        except RuntimeError:
            # No event loop — flush immediately (shouldn't happen in HA)
            self.flush_batch()

    def _cancel_flush_timer(self) -> None:
        """Cancel pending auto-flush timer."""
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

    def _fire_dp_commands(self, dpds: list[TuyaDatapointData]) -> None:
        """Fire-and-forget: send DPs in one Zigbee frame."""
        self.create_catching_task(
            self.command(
                self.mcu_write_command,
                TuyaCommand(
                    status=0,
                    tsn=self.endpoint.device.application.get_sequence(),
                    datapoints=dpds,
                ),
                expect_reply=False,
            )
        )

    # ── Helpers ─────────────────────────────────────────────────

    def _make_raw_dpd(self, dp: int, raw_bytes: bytes) -> TuyaDatapointData:
        """Create TuyaDatapointData with RAW dp_type."""
        data = TuyaData()
        data.dp_type = TuyaDPType.RAW
        data.raw = raw_bytes
        return TuyaDatapointData(dp, data)

    def _send_dp_command(self, dpd: TuyaDatapointData) -> None:
        """Send a single DP immediately (for non-light operations)."""
        self._fire_dp_commands([dpd])

    def _send_dp_commands(self, dpds: list[TuyaDatapointData]) -> None:
        """Send multiple DPs immediately (for non-light operations)."""
        self._fire_dp_commands(dpds)


    # ── Incoming DP parsing ─────────────────────────────────────

    # DPs handled by our custom ZCL clusters (not registered via builder)
    _CUSTOM_DPS = frozenset({1, 2, 3, 4, 51, 61})

    def handle_get_data(self, command) -> foundation.Status:
        """Override parent to route custom DPs through _dp_2_attr_update.

        The parent's handle_get_data only looks in data_point_handlers dict,
        which only contains DPs registered via the TuyaQuirkBuilder (51 scene
        select, 53 pixel count, 101/102/103 config). DPs 1/2/3/4/61 are
        handled by our custom ZCL clusters and must be routed here.

        IMPORTANT: This method is called from handle_cluster_request which
        wraps the call in `try: ... except AttributeError:`. If any code
        inside this method raises AttributeError, the parent catches it and
        logs "No 'handle_get_data' tuya handler found". We must be careful
        not to let AttributeErrors escape.
        """
        for record in command.datapoints:
            if record.dp in self._CUSTOM_DPS:
                try:
                    self._dp_2_attr_update(record)
                except Exception as exc:  # noqa: BLE001
                    self.warning("Error handling custom DP %s: %s", record.dp, exc)
            else:
                # Delegate builder-registered DPs to parent handler
                try:
                    dp_handler = self.data_point_handlers[record.dp]
                    getattr(self, dp_handler)(record)
                except (AttributeError, KeyError):
                    self.debug("No datapoint handler for %s", record)
        return foundation.Status.SUCCESS

    # Alias: set_data_response uses the same path as get_data
    handle_set_data_response = handle_get_data

    def _dp_2_attr_update(self, datapoint) -> None:
        """Parse incoming DP reports and update ZCL clusters."""
        dp = datapoint.dp

        # DP1: on_off → update OnOff cluster
        if dp == 1:
            on_off_cluster = self.endpoint.on_off
            if on_off_cluster:
                on_off_cluster._update_attribute(
                    OnOff.AttributeDefs.on_off.id,
                    bool(datapoint.data.payload),
                )
            return

        # DP3: brightness → update LevelControl cluster
        if dp == 3:
            level_cluster = self.endpoint.level
            if level_cluster:
                tuya_val = datapoint.data.payload  # 10-1000
                zcl_level = max(1, min(254, round((tuya_val - 10) * 253 / 990 + 1)))
                level_cluster._update_attribute(
                    LevelControl.AttributeDefs.current_level.id, zcl_level
                )
            return

        # DP4: color_temperature → update Color cluster
        if dp == 4:
            color_cluster = self.endpoint.light_color
            if color_cluster:
                tuya_val = datapoint.data.payload  # 0-1000
                mireds = round(370 - (tuya_val / 1000.0) * (370 - 153))
                color_cluster._update_attribute(
                    Color.AttributeDefs.color_temperature.id, mireds
                )
                color_cluster._update_attribute(
                    Color.AttributeDefs.color_mode.id, 2
                )
            return

        # DP2: work_mode → update Color cluster color_mode
        if dp == 2:
            mode = datapoint.data.payload
            color_cluster = self.endpoint.light_color
            on_off_cluster = self.endpoint.on_off
            level_cluster = self.endpoint.level

            if mode == 0:  # white mode
                if color_cluster:
                    color_cluster._update_attribute(
                        Color.AttributeDefs.color_mode.id, 2  # color_temp
                    )
            elif mode == 1:  # colour mode
                if color_cluster:
                    color_cluster._update_attribute(
                        Color.AttributeDefs.color_mode.id, 1  # xy
                    )
            elif mode == 2:  # scene mode
                # v6 FIX: Keep light entity showing "on" during scene playback.
                # The device is actively running a scene effect, so ensure
                # OnOff stays on and brightness stays at full.
                if on_off_cluster:
                    on_off_cluster._update_attribute(
                        OnOff.AttributeDefs.on_off.id, True
                    )
                if level_cluster:
                    level_cluster._update_attribute(
                        LevelControl.AttributeDefs.current_level.id, 254
                    )
                if color_cluster:
                    color_cluster._update_attribute(
                        Color.AttributeDefs.color_mode.id, 1  # xy
                    )
            elif mode == 3:  # music mode
                if on_off_cluster:
                    on_off_cluster._update_attribute(
                        OnOff.AttributeDefs.on_off.id, True
                    )
                if level_cluster:
                    level_cluster._update_attribute(
                        LevelControl.AttributeDefs.current_level.id, 254
                    )
                if color_cluster:
                    color_cluster._update_attribute(
                        Color.AttributeDefs.color_mode.id, 1  # xy
                    )
            # v6 FIX: Do NOT call super()._dp_2_attr_update() for DP2.
            # The parent TuyaMCUCluster looks for a registered datapoint
            # handler for DP2, but we never registered one via the builder
            # (DP2 is handled entirely by our custom ZCL clusters).
            # Calling super() causes "No datapoint handler for dp=2" warnings.
            return

        # DP61: SmearFormater color data → update Color cluster XY
        if dp == 61 and datapoint.data.dp_type == TuyaDPType.RAW:
            raw = datapoint.data.raw
            if len(raw) >= 11:
                hue = struct.unpack(">H", raw[5:7])[0]
                sat = struct.unpack(">H", raw[7:9])[0]
                val = struct.unpack(">H", raw[9:11])[0]
                self._current_hue = hue
                self._current_saturation = sat
                self._current_value = val
                color_cluster = self.endpoint.light_color
                if color_cluster:
                    xy = _hs_to_xy(hue, sat)
                    color_cluster._update_attribute(
                        Color.AttributeDefs.current_x.id, xy[0]
                    )
                    color_cluster._update_attribute(
                        Color.AttributeDefs.current_y.id, xy[1]
                    )
                    color_cluster._update_attribute(
                        Color.AttributeDefs.color_mode.id, 1
                    )
                level_cluster = self.endpoint.level
                if level_cluster and val > 0:
                    zcl_level = max(1, min(254, round(val * 254 / 1000)))
                    level_cluster._update_attribute(
                        LevelControl.AttributeDefs.current_level.id,
                        zcl_level,
                    )
            return

        # DP51: scene data — ignore incoming
        if dp == 51 and datapoint.data.dp_type == TuyaDPType.RAW:
            return

        # Everything else: delegate to parent for MCU attribute mapping
        super()._dp_2_attr_update(datapoint)

    # ── Scene playback (used by the HA light-effect patch, light_effects.py) ──

    def play_scene(self, scene_index: int) -> None:
        """Play a dreamlight scene by its ScenePreset index (0..43).

        Sends DP1=on + DP2=scene_mode + DP51=raw scene data in one frame
        (matching the SmartLife app / Zigbee2MQTT approach for GL-SPI-206P) and
        updates local OnOff/Level state so the light entity shows on at full.
        Exposed as HA light *effects* by light_effects.py's monkey-patch; the
        raw payloads are in SCENE_DATA and the names in SCENE_NAMES.
        """
        scene_bytes = SCENE_DATA.get(int(scene_index))
        if scene_bytes is None:
            self.warning("Unknown scene index: %s", scene_index)
            return
        self._send_dp_commands([
            TuyaDatapointData(1, TuyaData(t.Bool(True))),
            TuyaDatapointData(2, TuyaData(t.enum8(0x02))),
            self._make_raw_dpd(51, scene_bytes),
        ])
        # Update local state to reflect scene is active and light is on
        on_off_cluster = self.endpoint.on_off
        if on_off_cluster:
            on_off_cluster._update_attribute(OnOff.AttributeDefs.on_off.id, True)
        level_cluster = self.endpoint.level
        if level_cluster:
            level_cluster._update_attribute(
                LevelControl.AttributeDefs.current_level.id, 254
            )

    # ── Command bus handler (config DPs 53/101/102/103) ──

    def tuya_mcu_command(self, cluster_data: TuyaClusterData):
        """Delegate command-bus writes to the parent.

        Light DPs (1/2/3/4/61) are handled directly by the ZCL clusters via
        queue_dp/queue_color_*/flush_batch; scenes are sent via play_scene()
        (from the light-effect patch). Everything else — the config DPs
        (pixel_count 53, colour_order 101, chip_type 102, DND 103) — is handled
        by the parent TuyaMCUCluster.
        """
        super().tuya_mcu_command(cluster_data)


# ────────────────────────────────────────────────────────────────
# Quirk V2 — TuyaQuirkBuilder
# ────────────────────────────────────────────────────────────────

(
    TuyaQuirkBuilder("_TZE284_gt5al3bl", "TS0601")
    # ── Force device type to EXTENDED_COLOR_LIGHT so ZHA creates light.* entity ──
    .replaces_endpoint(1, device_type=zha.DeviceType.EXTENDED_COLOR_LIGHT)
    # ── Light entity clusters (creates HA light.* entity) ──
    .adds(TuyaSPIOnOffNM)
    .adds(TuyaSPILevelControl)
    .adds(TuyaSPIColorControl)
    # ── Scenes are exposed as HA light *effects* (light_effects.py monkey-patch),
    #    not as a select entity — the 44 scenes live in SCENE_DATA/SCENE_NAMES and
    #    are played via TuyaSPILightMCUCluster.play_scene(). ──
    # ── Pixel count (CONFIG) ──
    .tuya_number(
        dp_id=53,
        type=t.uint16_t,
        attribute_name="pixel_count",
        min_value=10,
        max_value=1000,
        step=1,
        entity_type=EntityType.CONFIG,
        translation_key="pixel_count",
        fallback_name="LED pixel count",
    )
    # ── Chip type (CONFIG) ──
    .tuya_enum(
        dp_id=102,
        attribute_name="chip_type",
        enum_class=ChipType,
        entity_type=EntityType.CONFIG,
        translation_key="chip_type",
        fallback_name="LED chip type",
    )
    # ── Color order (CONFIG) ──
    .tuya_enum(
        dp_id=101,
        attribute_name="color_order",
        enum_class=ColorOrder,
        entity_type=EntityType.CONFIG,
        translation_key="color_order",
        fallback_name="Color order",
    )
    # ── Do not disturb (CONFIG) ──
    .tuya_switch(
        dp_id=103,
        attribute_name="do_not_disturb",
        entity_type=EntityType.CONFIG,
        translation_key="do_not_disturb",
        fallback_name="Do not disturb",
    )
    # ── Enchantment for periodic state polling ──
    .tuya_enchantment()
    .skip_configuration()
    .add_to_registry(replacement_cluster=TuyaSPILightMCUCluster)
)
