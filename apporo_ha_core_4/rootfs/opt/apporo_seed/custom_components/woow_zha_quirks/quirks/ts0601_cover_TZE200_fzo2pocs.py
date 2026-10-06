"""ZHA Quirk for Tuya TS0601 roller-shade motor _TZE200_fzo2pocs (18-ZM25TQ).

Zemismart ZM25TQ 管狀捲簾電機 (tubular roller-shade motor) — TZE200 protocol.

Without this quirk the device matches the upstream v1 quirk
``zhaquirks.tuya.ts0601_cover.TuyaZemismartSmartCover0601_3``, which exposes only a bare
cover entity (open/close/stop/position) plus an OTA ``update.*`` entity. This v2
TuyaQuirkBuilder quirk takes precedence (v2 wins over v1).

DP map (Tuya cloud thing-model, see tuya_export/DP_REFERENCE.md → 18-ZM25TQ):
  DP1   - ENUM  - control: open / stop / close / continue
  DP2   - VALUE - set target position (0-100 %)
  DP3   - VALUE - current position report (0-100 %, ro)
  DP5   - ENUM  - control_back motor direction: 0=forward, 1=back
  DP7   - ENUM  - work_state: opening / closing (ro; reflected by cover state)
  DP11  - ENUM  - situation_set: fully_open / fully_close (ro; 100 % = fully open)
  DP12  - BITMAP- fault: motor_fault (ro)
  DP101 - BOOL  - remote_register (remote pairing)   ── not exposed (see below)
  DP102 - BOOL  - reset_limit (reset all limits)      ── not exposed
  DP103 - BOOL  - up_confirm (upper limit)             ── not exposed
  DP104 - BOOL  - middle_confirm (middle limit)        ── not exposed
  DP105 - BOOL  - down_confirm (lower limit)           ── not exposed
  DP106 - ENUM  - motor_mode: 0=contiuation (linkage), 1=point (inching)

Design: the ZM25TQ's **upper/lower limits can only be set with the physical RF remote** —
the Tuya app itself cannot set them over the network (verified by sniffing the app, see
docs/18-ZM25TQ-sniff-findings.html, and corroborated by the wider ZM25TQ community). So the
limit / jog / reset datapoints are deliberately **not exposed** here — they would be
misleading. Once the motor is calibrated with its remote, the plain ``cover`` entity controls
it correctly (ZHA speaks the same ef00 DP1 protocol the Tuya app uses).

Exposed: a ``cover`` (DP1 open/stop/close, DP2 set %, DP3 report %) and a Motor Direction
switch (DP5). Motor mode (DP106) is fixed to **Linkage** (continuous run-to-limit, required for
a cover) and not exposed as an entity — it is mapped (hidden) only so it can be written to
Linkage and so DP106 reports don't log "no datapoint handler". Also suppressed: the OTA update
entity and the ZCL WindowCovering "type" (窗簾類型) diagnostic sensor.

Position invert: **``invert=True`` is confirmed correct** (verified live 2026-07-02 with the
remote-calibrated limits: HA read 77 % open ⇔ curtain physically ~77 % open). The ZCL/HA/Tuya
percentage conventions cancel out, so despite situation_set=fully_open the ``invert=True`` default
is right — do NOT flip it to False.
"""

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zhaquirks.tuya.builder import TuyaQuirkBuilder

WINDOW_COVERING = 0x0102  # ZCL WindowCovering cluster id


class MotorMode(t.enum8):
    """Motor operating mode (DP106)."""
    Linkage = 0x00   # contiuation 連動 (continuous run-to-limit — required for a cover)
    Inching = 0x01   # point 點動


(
    TuyaQuirkBuilder("_TZE200_fzo2pocs", "TS0601")
    .tuya_cover(
        control_dp=1,
        position_state_dp=3,
        position_control_dp=2,
        invert=True,
    )
    # ── Motor direction (DP5) — a real forward/back state → switch ──
    .tuya_switch(
        dp_id=5,
        attribute_name="motor_direction",
        entity_type=EntityType.CONFIG,
        translation_key="motor_direction",
        fallback_name="Motor Direction",
    )
    # ── Motor mode (DP106) — mapped hidden (no entity); fixed to Linkage ──
    # Not exposed: a cover must run to its limits (Linkage); Inching would only jog.
    # Kept mapped so ZHA can write Linkage and so DP106 reports aren't dropped as
    # "no datapoint handler".
    .tuya_dp_attribute(dp_id=106, attribute_name="motor_mode", type=MotorMode)
    # ── Suppress noise entities ──
    # ZCL WindowCovering "type" (窗簾類型) diagnostic — meaningless for this motor.
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=WINDOW_COVERING,
        unique_id_suffix="window_covering_type",
    )
    # Redundant firmware/OTA update entity.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .skip_configuration()
    .add_to_registry()
)
