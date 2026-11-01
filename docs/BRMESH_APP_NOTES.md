# BRMesh app: findings from the decompiled source

Notes from the decompiled Android app (`cn.com.broadlink.blelight.helper.BLEFastconHelper`, `BLSBleLight` and a group UI fragment), plus packets captured with `tools/brmesh_debug.py`. These are reference notes for future work on fastConLight; [SPECIFICATION.md](../SPECIFICATION.md) stays the design document. Items marked *(guess)* aren't confirmed.

Packet building and encryption happen in a native library (`cn.com.broadlink.blelight.jni.BLEUtil`, JNI). The Java side only gives function names and parameters for those parts.

## Contents

1. [Constants](#1-constants)
2. [Device types](#2-device-types)
3. [Mesh addresses](#3-mesh-addresses)
4. [Building a packet](#4-building-a-packet)
5. [Sending](#5-sending)
6. [Receiving](#6-receiving)
7. [Groups](#7-groups)
8. [Captured packets](#8-captured-packets)
9. [Open questions](#9-open-questions)
10. [Follow-ups for the integration](#10-follow-ups-for-the-integration)

## 1. Constants

| Constant | Value | Meaning |
|---|---|---|
| `BLE_FASTCON_ADDRESS` | `C1 C2 C3` | RF address used in `get_rf_payload` (same as ours) |
| `BLE_FASTCON_HEADER_LENGTH` | 4 | |
| `BLE_FASTCON_MAX_LENGTH` | 16 | old-protocol body (4 header + 12 data) |
| `BLE_FASTCON_PAYLOAD_MAX_LENGTH` | 12 | old-protocol data |
| `BLE_FASTCON_NEW_MAX_LENGTH` | 22 | new-protocol body (4 + 18) |
| `BLE_FASTCON_PAYLOAD_NEW_MAX_LENGTH` | 18 | new-protocol data |
| `BLE_FASTCON_NEW_MAX_LENGTH_PATH_THROUGH` | 25 | pass-through frames |
| `BLE_FASTCON_TYPE_DISCOVER_TOGGLE` | 0 | scan |
| `BLE_FASTCON_TYPE_DISCOVER_REQ` | 1 | discovery broadcast from a light |
| `BLE_FASTCON_TYPE_DISCOVER_RES` | 2 | bind |
| `BLE_FASTCON_TYPE_UPLOAD_REQ` | 3 | status / heartbeat from a light |
| `BLE_FASTCON_TYPE_UPLOAD_RES` | 4 | |
| `BLE_FASTCON_TYPE_CONTROL_REQ` | 5 | control |
| `BLE_FASTCON_TYPE_CONTROL_RES` | 6 | |
| `BLE_FASTCON_TYPE_REMOTE_CTRL` | 7 | remote control |
| `BLE_CMD_SEND_TIME` | 3000 ms | advertising time per command (our default comes from here) |
| `BLE_CMD_RETRY_CNT` | 1 | |
| `CMD_LIGHT_ON` | `FF` | on, full brightness |
| `CMD_LIGHT_OFF` | `00` | off |
| `CMD_GROUP_LIGHT_ON` | `7F` | "group on" (no on bit); where the app uses it is unknown |
| `BLE_LIGHTNESS_MIN` / `MAX` | 5 / 127 | brightness range; ours goes down to 1 |
| `BLE_CW_MIN` / `MAX` | 0 / 255 | |
| `BLE_JIFFIES_CNT_PER_SEC` | 64 | timers/effects; min 1, max 101 |
| `BLE_BATCH_CTRL_MAX_CNT` | 15 | |
| `BLE_BATCH_CTRL_MAX_CNT_IN_DEV` | 5 | lights per batch packet *(guess)* |
| `BLE_BATH_TEMP_GROUP_DEVICE_MAX` | 104 | address span per temp-group packet (13-byte bitmap? *(guess)*) |
| `VISUALIZER_CNT` | 8 | music mode |
| Default phone key | `A1 A2 A3 A4` | `mPhoneKey` |

Sequence numbers start at `currentTimeMillis % 256`; 0 and 256 wrap to 1. On an inner retry (`mSendCnt < 5` and `high > 1`) the sequence jumps +10 instead of +1.

## 2. Device types

Decimal values are what the app uses; hex is calculated. All nine light types in `protocol.py` (`LIGHT_TYPE_NAMES`) match.

**Corrections needed in SPECIFICATION.md §5 and `DEVICE_TYPE_NAMES`:**
- **Fan = 44049**, not 43531.
- **43463 / 43462 = Relay 3 / Relay 3 wireless.** They are not "Panel 3": the app has no Panel 3.

### Lights

| Constant | Dec | Hex |
|---|---|---|
| LIGHT_PWR | 43049 | A829 |
| LIGHT_RGBCW | 43050 | A82A |
| LIGHT_CCT | 43051 | A82B |
| LIGHT_RGB | 43168 | A8A0 |
| LIGHT_RGBW | 43169 | A8A1 |
| LIGHT_COMPOSE | 43709 | AABD |
| LIGHT_W_CW | 43745 | AAE1 |
| LIGHT_BURDEN_CW | 43754 | AAEA |
| LIGHT_BURDEN_W | 43759 | AAEF |
| TV_BACKLIGHT | 43990 | ABD6 |
| LIGHT_W_24G_QLM | 44060 | AC1C |
| LIGHT_OEM_HEXAGON | 44235 | ACCB |
| CAMP_LAMP | 44483 | ADC3 |
| LIGHT_CW_RGB | 44493 | ADCD |
| LIGHT_CW_CW | 44495 | ADCF |
| LIGHT_W_24G | 44601 | AE39 |
| LIGHT_CW_CW_LS | 44838 | AF26 |
| LIGHT_PWR_SELF_LEARN | 44876 | AF4C |
| LIGHT_DAZZLE_NEW | 44935 | AF87 |
| LIGHT_RGBCW_HSL | 45510 | B1C6 |
| LIGHT_PWR_GREE_1…5 | 45543, 45545, 45547, 45549, 45551 | B1E7 … B1EF |
| LIGHT_CCT_GREE_2, 3, 1, 4, 5 | 45544, 45546, 45548, 45550, 45552 | B1E8 … B1F0 |
| LIGHT_PWR_SELF_LEARN_ADC | 45559 | B1F7 |
| LIGHT_CCT_FSL_1 | 45648 | B250 |
| LIGHT_W_HIGH_V | 45655 | B257 |
| LIGHT_PWR_SELF_LEARN_1 | 45776 | B2D0 |
| LIGHT_CCT_1 | 45852 | B31C |
| LIGHT_CCT_2 | 45854 | B31E |
| LIGHT_PWR_1 | 45855 | B31F |
| LIGHT_RGBCW_1 | 45856 | B320 |

### Switches, relays, sockets

| Constant | Dec | Hex |
|---|---|---|
| RELAY_3_WIRELESS | 43462 | A9C6 |
| RELAY_3 | 43463 | A9C7 |
| RELAY_2 | 43474 | A9D2 |
| RELAY_1 | 43525 | AA05 |
| RELAY_4 | 43680 | AAA0 |
| CARD_POWER | 43992 | ABD8 |
| SOCKET_4, 5, 6, 3 | 44164, 44165, 44166, 44167 | AC84 … AC87 |
| SOCKET_2, 1 | 44180, 44181 | AC94, AC95 |
| RELAY_CURTAIN_1, 2 | 44606, 44607 | AE3E, AE3F |
| RELAY_1_OEM_FSL | 44624 | AE50 |
| SOCKET_1_OEM_JP | 45124 | B044 |
| SOCKET_3_OEM_JP | 45485 | B1AD |
| SOCKET_5_OEM_JP | 45495 | B1B7 |
| RELAY_2_OEM_JP | 45746 | B2B2 |
| SIG_RELAY | 45853 | B31D |

### Panels and remotes

| Constant | Dec | Hex |
|---|---|---|
| PANEL_6_WIRELESS | 43459 | A9C3 |
| PANEL_6 | 43461 | A9C5 |
| PANEL_4_WIRELESS | 43472 | A9D0 |
| PANEL_4 | 43473 | A9D1 |
| META_PAD | 43518 | A9FE |
| PANEL_8 | 43733 | AAD5 |
| PANEL_8_2 | 43734 | AAD6 |
| SMART_PAD_8 | 43981 | ABCD |
| VIRTUAL_MULTI_PANEL | 44063 | AC1F |
| META_PAD_ABILITY | 44199 | ACA7 |
| META_PAD_SINGLE | 44211 | ACB3 |
| META_PAD_KNOB | 45764 | B2C4 |

### Curtains, motors, household

| Constant | Dec | Hex |
|---|---|---|
| CURTAIN | 43499 | A9EB |
| DRYING_RACK | 44007 | ABE7 |
| FAN | 44049 | AC11 |
| CURTAIN_OPEN_CLOSE | 44111 | AC4F |
| CURTAIN_ROLL | 44112 | AC50 |
| CURTAIN_DREAM | 44113 | AC51 |
| COMMON_MOTOR | 44243 | ACD3 |
| JUMP_ROPE | 44313 | AD19 |
| AIR_CLOUD_BUTLER | 44603 | AE3B |
| CURTAIN_WSD_BLIND | 44724 | AEB4 |
| CURTAIN_WSD_DAY_NIGHT | 44725 | AEB5 |
| CURTAIN_WSD_DUAL | 44726 | AEB6 |
| DRYING_RACK_WSD | 44727 | AEB7 |
| DRYING_RACK_WSD_FULL | 44728 | AEB8 |
| DRYING_RACK_WSD_DUAL | 44729 | AEB9 |
| DOOR_MAGLEV | 45035 | AFEB |
| DOOR_LOCK | 45127 | B047 |
| CURTAIN_RM | 45153 | B061 |
| DRYING_PANEL3 | 45165 | B06D |
| TC_1, TC_2, TC_3 | 45399, 45401, 45402 | B157, B159, B15A |
| ELE_METER | 45512 | B1C8 |
| BED | 45522 | B1D2 |
| CURTAIN_SHADE_RM | 45610 | B22A |
| GARAGE_DOOR | 45733 | B2A5 |
| DONGLE | 45739 | B2AB |
| GARAGE_DOOR_1 | 45767 | B2C7 |
| TIMER | 45798 | B2E6 |
| VIDEO_DOOR_LOCK | 70731 | 1144B (above 16 bits) |
| VIDEO_DOOR_LOCK_MS | 70759 | 11467 (above 16 bits) |

### Sensors

| Constant | Dec | Hex |
|---|---|---|
| SENSOR_DOOR | 43505 | A9F1 |
| SENSOR_IR | 43516 | A9FC |
| SENSOR_WATER | 43791 | AB0F |
| SENSOR_RADAR | 43808 | AB20 |
| SENSOR_OEM_MMC | 43951 | ABAF |
| SENSOR_SOS | 44207 | ACAF |
| SENSOR_FOUR_LINE | 44209 | ACB1 |
| BEACON_WSD | 44274 | ACF2 (name prefix "XL08") |
| SENSOR_ILLUMINANCE_LS | 44571 | AE1B |
| SENSOR_RADAR_24G | 44619 | AE4B |
| SENSOR_GAS | 44880 | AF50 |
| SENSOR_SMOKE | 44895 | AF5F |
| SENSOR_RADAR_24G_1 | 45477 | B1A5 |
| SENSOR_SOUND_LIGHT | 45558 | B1F6 |
| SENSOR_ILLUMINANCE | 45652 | B254 |
| SENSOR_RAIN | 45659 | B25B |
| SENSOR_SOS_CLD | 45836 | B30C |

### Gateways and climate

| Constant | Dec | Hex |
|---|---|---|
| GATEWAY_IHG | 10058 | 274A |
| GATEWAY_OEM_RMAC | 21025 | 5221 |
| GATEWAY_OEM_BLACK_BEAN | 21028 | 5224 |
| GATEWAY | 43500 | A9EC |
| GATEWAY_AC | 43756 | AAEC |
| THERMOSTAT | 43919 | AB8F |
| GATEWAY_LAN | 44602 | AE3A |
| GATEWAY_RMAC | 44939 | AF8B |
| GATEWAY_1 | 45106 | B032 |
| GATEWAY_TOIC_PAD | 45525 | B1D5 |

`RM_SUB_DEV_TYPE` (IR/RF remote sub-devices of an RM gateway) reuses some codes, e.g. AC 43919, TV 44843, light 45152, curtain 45153. These are virtual devices, not mesh nodes.

## 3. Mesh addresses

| Address | Meaning |
|---|---|
| 0 | all lights. The app sends "all on" here (captured, §8) |
| 240–243 | `BLE_ROOM_SCENE_DEFAULT`: room/scene addresses |
| 253 | `BLE_TEMP_GROUP_DEV_CONTROL_ID`: temporary group |
| 254 | `BLE_TEMP_GROUP_DEV_MUSIC_ID`: music group |
| 255 | `BLE_FASTCON_GATEWAY_ADDRESS` / `BLE_TEMP_GROUP_DEV_RESERVE_ID` |

- `MAX_ADDRESS_CNT = 255`, but the app also keeps `mQueueDevAddress4096`: addresses up to 4095 exist. The high bits go in the header's low nibble (our `address_high`, the `high` parameter below).
- The integration currently hands out and accepts 1–255, so 240–255 can collide with groups (see §10).

## 4. Building a packet

From `getPayloadWithInnerRetry` / `getPayloadWithSrcAddr`:

```
BLEUtil.package_ble_fastcon_body(type, high % 255, seq, safeKey, forwardFlag,
                                 data, dataLen, out, phoneKey)
```

- `type`: header type (5 = control).
- `high`: mesh address / 256, the header's low nibble.
- `safeKey`: `phoneKey[3]`, or `0xFF` when no key. Matches our `package_body`.
- `forwardFlag`: from `getForwardFlag(z)` / `mGlobalForwardFlag`.
- Old protocol: data ≤ 12 bytes → 16-byte body. New protocol: data padded to 18 → 22-byte body.
- `package_ble_fastcon_body_nor_encryp` builds the same body unencrypted (for the app's log only).

Making the advertisement (`doSendCommand`):
- Old protocol: `BLEUtil.get_rf_payload(C1C2C3, data)` → whitened RF frame, sent as manufacturer data `0xFFF0`. This matches our `get_rf_payload`.
- New protocol: `BLEUtil.bl_get_ble_payload(data, len, out[len + 2], …)` → frames starting `a5 5a` *(native, layout unknown)*.
- Non-connectable advertising prepends `00 00 00` to the manufacturer data.

Key for the data part per header type (confirmed with real frames; the header is always XORed with the default key `5E 36 7B C4`):

| Type | Data encrypted with |
|---|---|
| 0 scan | default key |
| 1 discovery | not encrypted (DID, type, device key in the clear) |
| 2 bind | the light's device key |
| 3–7 heartbeat, status, control | phone key |

The checksum (header byte 3) is the sum of header bytes 0–2 and the *decrypted* data, so it only matches with the right key.

Single light control data (confirmed): `[2 | (len + 1) << 4] [address low byte] [command…]`, control type 2 in the low nibble.

Other native packers seen: `package_sync_time_info` (time sync, sent with type 5 to all), `package_gateway_config`, `package_fixed_group_create`, `package_fixed_group_remove`, `package_batch_temp_group`, `send_aok_ctrl_handler`, `send_sr_ctrl_handler`.

## 5. Sending

- Android advertiser: mode 2 (low latency, about 100 ms), connectable, TX power 3 (high), no timeout.
- Each command is advertised `BLE_CMD_SEND_TIME` = 3 s.
- Batches (`doSendBatchCommand`) are scheduled on a handler, `count × interval` apart.
- `broadcastAppTimeSync`: `sendCommand(5, package_sync_time_info(...), phoneKey, retry 1, 3000 ms, ...)`. This is the minute-by-minute time sync to address 0 (§7.3 in the spec).

## 6. Receiving

`doDealWithScanResult` classifies frames (raw advertisement hex, after the flags AD):

| Starts with / contains | Kind | Handling |
|---|---|---|
| `13 ff f0 ff` or `1b ff f0 ff`, not `a5 5a` | old protocol (16 or 24 bytes) | `parseOldProtocolPayload` |
| contains `f0 ff 6d b6 43 68 93 1d` | whitened RF frame (what we send, what lights relay) | `parseDevCtrlUpload` → old-protocol parser. Our `unwrap_rf_frame` covers this. |
| `1b ff f0 ff a5 5a` | new protocol, 22 bytes | `parseNewProtocolPayload` |
| contains `f0 ff a5 5a` | pass-through, 25 bytes | `parsePassThroughPayload` |
| name starts with `XL08` | beacon sensor | special parsing |

- Repeats are filtered (`RepeatPackageFilterHelper`).
- Heartbeats are accepted from any address (already in the spec).

## 7. Groups

### Fixed groups
`broadcastFixedGroupId(groupId, addrs, …)` → `package_fixed_group_create(addrBytes, baseAddr, n, groupId, out18)`, new protocol.
- Lights store the group id. *(guess)* This is the heartbeat's group byte (`parse_heartbeat` `group_address`).
- The UI controls a fixed group directly with `groupId` and sends nothing beforehand.
- Removing: `package_fixed_group_remove(addrs, n, groupIds, m, groupId, out18)`.

### Temporary groups
`BLSBleLight.broadcastTempGroupId(int[] addrs)` calls:

```
broadcastTempGroupId(253, addrs, cookie = (short) currentTimeMillis, sendTime = 150, repeats = 3)
```

1. `calcHighArrays` splits the addresses by high byte (address / 256). One `BatchPayload` per high byte.
2. Within that, addresses are grouped into spans of 104 from the lowest address, at most 3 spans. Each span gives one 18-byte payload: `package_batch_temp_group(lowBytes, n, 253, cookie, out18)`, new protocol.
3. Each payload is sent 3× at 150 ms. The return value is `150 × 3 × packets` ms (≈ 0.45 s for up to 104 lights). The UI shows "Loading" for that long.
4. Afterwards the group is controlled through address 253 *(guess; control method in `DeviceCtrlActivity` not seen)*.
5. The app treats every group as RGBCW (`type = BLE_DEV_TYPE_LIGHT_RGBCW`).

UI logic (group fragment `B()`): if `getPhoneType() == 1 && type == 0`, it opens control with `groupId`, `tempGroupId = -1` (fixed group). Otherwise it sets up a temp group first.

## 8. Captured packets

Phone key `A1A2A3A4`. Decoded with `decode <hex>` in the debug tool.

**Heartbeat from a light, mesh address 18** (after a successful bind), flags `02`:
```
6e 6c 69 bc d5 b0 a3 a0 a5 97 a9 ab a1 a2 a3 a4
header 30 5a 12 78   type 3, seq 90, checksum ok
data   74 12 00 04 04 35 0a 0f 00 00 00 00
       subtype 4 (heartbeat), address 0x12 = 18, group 0, rest unknown (status/version?)
```

**"All on" to address 0**, flags `1a`. First taken for the phone app; more likely a light's relay of a command (see the next capture):
```
6d b6 43 68 93 1d dd 91 07 57 1b aa 78 6f 9a 5e d2 07 55 f7 cb 6b bd bb   (RF frame)
header d0 94 a4 29   type 5, forward, seq 148, safe key a4, checksum ok
data   22 00 ff …    control type 2, length 1, address 0, command ff
```

**"All off" to address 0, relayed by a light** (flags `1a`, seq 36): `6d b6 43 68 93 1d dd 21 07 c4 1b aa 87 6f 9a 5e d2 07 55 f7 cb 6b c6 d9`, data `22 00 00`. The light received, decrypted and forwarded our command but did **not** switch off.

Flags seen so far: heartbeats and discovery from lights `02`; relayed control frames `1a` (likely, not confirmed). Our ESP32 and the HA adapter send `02`. Whether the phone app sends `1a` is open.

**"All on" from the BRMesh app** (user capture, 2026-11-01). The raw frame and the user's phone key are left out on purpose: the key can be read back from raw frames (see below). Decrypted:
```
header type 5, forward, checksum ok
phone key: the user's app mesh (not A1A2A3A4), read from the zero padding
data   43 2a a8 00 80 00 …
       control type 3 (not 2), 4 bytes follow: 2a a8 = device type 0xA82A (Light RGBCW), then 00 80
```
So the app's "all on" addresses **all lights of one device type** (control type 3), not address 0. `00` is probably a group/high byte and `80` the command (on bit, level 0 = "on, keep brightness"?) *(guess)*. The debug tool now guesses another mesh's phone key from the zero padding (data bytes 8–11) and shows control type 3.

**"All off" from the BRMesh app**: data `43 2a a8 00 00` (same as "all on" with command `00`).

**Reading a phone key from a frame:** data bytes 8–11 are usually zero, so the encrypted bytes there are the key itself (header byte 2 = its last byte confirms it). Never publish raw frames of a private mesh.

**Control type 3 layout (confirmed):** `[3 | (len(command) + 3) << 4] [device type lo] [device type hi] [00] [command…]`. Implemented as `CommandBuilder.light_by_type()`; the integration's "All lights" sends one per light type in the mesh. Our frames match the app's byte for byte except the 2-byte RF CRC, which differs by a constant XOR `ef 79` in both captures. Lights relay our frames with our CRC (a relayed "all on" matched ours exactly), so they accept it.

**Type filter test** (user's two lights, their app mesh key, 2026-11-01): `off type:A82A` (RGBCW) and `off type:A8A1` (RGBW) each switch **both** lights; `off type:A82B` (CCT) switches neither. The lights relay it (data `43 2b a8 00 00`) but don't execute it. So the device type is a filter, but RGBW/RGBCW lights accept each other's type (or RGBW lights also accept RGBCW, the type the app uses for groups) *(open: exact types of the two lights)*. The integration therefore sends one command per light type in the mesh.

**Groups ("Flur", user captures 2026-11-01, decrypted; raw frames left out):**
```
add light 2 to Flur:  21 02 01   control type 1, not forwarded: [1 | 2 << 4] [mesh address] [group id]
add light 4 to Flur:  21 04 01
remove light 4:       21 04 00   group 0 = no group
Flur off:             43 2a a8 01 00   control type 3 with group id 1 (all off was group 0)
```
So control type 3 is `[3 | (len + 3) << 4] [type lo] [type hi] [group] [command]`: **group 0 = all lights**, other ids = fixed groups. Groups are plain old-protocol commands, not the `a5 5a` frames. Implemented: `CommandBuilder.assign_group()`, `light_by_type(..., group=)`; debug tool `group add/remove` and targets `group:<id>`; integration 2.21.0: groups under Configure → Groups, one light entity per group. A light stores one group byte, so it is in at most one group; assigning another group replaces it, group 0 removes it. Open: how the app picks ids (1, 2, …?), whether the heartbeat's group byte shows the group.

**Effects** (second BRMesh-type app, light at mesh address 16, decrypted; raw frames and key left out):
```
Full color fade:   88 10 01 42 03 01 05 04 06   fade red, magenta, blue, cyan, green, yellow
Romantic slow:     48 10 01 43 02               fade magenta, red
Romantic fast:     48 10 64 43 02               same, speed 100
Fresh:             58 10 2a 45 01 04            fade cyan, blue, green, speed 42
```
**Layout (decoded with the app's `BLESceneInfo`, z30.b/e/f/g):** a scene is `jiffies` (speed), `mode` (0 or 1) and a list of `RgbStatus` (red/green/blue on or off): `[8 | (2 + n) << 4] [mesh address] [speed 1-100] [mode << 6 | colour 1] [colour 2] … [colour n]`. Colour bits are in the blue-red-green order of the colour command: **bit 0 blue, bit 1 red, bit 2 green** (1 blue, 2 red, 3 magenta, 4 green, 5 cyan, 6 yellow, 7 white, 0 off), confirmed by the user (red/yellow sent with the wrong order showed blue/pink) and by "Full color fade" matching the app's default list red, magenta, blue, cyan, green, yellow exactly. The app's own `mode` field is inverted: app mode 0 = fade (bit 6 set in the frame), app mode 1 = flash (bit 6 clear). A single colour gets "off" added. Implemented: `CommandBuilder.scene()`, debug tool `scene <addr> <speed> <fade|jump> <colours…>` and a colour builder. **Stopping (tested):** a colour or white command (6-byte form) ends the effect and sets that colour; the short on command (`0x80 | level`) doesn't; off switches the light off, and after on the effect continues (the light keeps the effect as its state). Open: confirm mode 0 (jump).

**The app's 21 predefined effects** (strings `Mod1`–`Mod21`, built in a fragment's `B(int jiffies)` switch; `Mod22`/`Mod23` are "DIY flash/fade 1" from the user's own colours):

| # | Name | Mode | Colours |
|---|---|---|---|
| 1 | Full color fade | fade | red, magenta, blue, cyan, green, yellow |
| 2 | Romantic | fade | magenta, red |
| 3 | Fresh | fade | cyan, blue, green |
| 4 | Cozy | fade | yellow, red |
| 5 | Full color flash | flash | red, magenta, blue, cyan, green, yellow |
| 6 | Three color flash | flash | red, green, blue |
| 7 | Yellow and green flash | flash | yellow, green |
| 8 | Purple and green flash | flash | magenta, green |
| 9 | Purple and blue flash | flash | magenta, blue |
| 10 | Yellow and purple flash | flash | yellow, magenta |
| 11 | Red and green flash | flash | red, green |
| 12 | Red and blue flash | flash | red, blue |
| 13 | Green and blue flash | flash | green, blue |
| 14–17 | Red / Green / Blue / White flash | flash | that colour, off |
| 18 | Christmas | fade | red, green |
| 19 | Winter | fade | blue, white |
| 20 | Halloween | fade | green, white |
| 21 | Valentines day | fade | red, white |

The speed comes from the app's slider (`jiffies`). These are the integration's default effects; existing meshes get them with Configure → Effects → "Add the BRMesh app's built-in effects".

Other effect-related calls seen (not decoded): `controlDelaySceneWithDevice` with `BLEDelaySceneInfo` (start brightness, step ±1, count, interval: timed fade-in/out), `controlColorChange` and `controlRgbcwModeV2` with lists of full RGB `BLEModeRgbcwBean` (custom colour modes, probably another frame format).

**Discovery from a light (test data):** type `a1 a8` = 43169 Light RGBW, used in `test_describe_action_from_real_broadcasts`.

## 9. Open questions

- **Phone keys:** the user's app mesh uses its own key; lights bound by HA/the debug tool use `A1 A2 A3 A4`. Lights only execute commands with their own key, which may explain commands that are relayed but not executed.
- **Solved:** "all off" via address 0 doesn't work; the app uses control type 3 per device type (see §8). Was: (reported 2026-11-01). The lights relay it (so key and checksum are fine) but don't execute it; "on" (`ff`) to address 0 works. Candidates to try with `cmd all <hex>`: `80` (on bit, level 0), `00 00 00 00 00 00` (6-byte colour form, off), `7f`/`00` variants; or capture the app's "all off".
- **New-protocol frame layout** (`a5 5a`, `bl_get_ble_payload`): is it whitened? Which keys? The debug tool shows both readings and the checksum.
- **Byte layout of `package_batch_temp_group` / `package_fixed_group_create`**: start address + bitmap *(guess)*. Needs a capture of the app setting up a group of known lights.
- **How a group is switched**: which address (253, 240–243, group id), which control type, `FF` or `7F`.
- **Batch control** (`BLE_BATCH_CTRL_MAX_CNT_IN_DEV = 5`): several lights in one packet? Not seen in the pasted code.
- Heartbeat data bytes 3–7 (`04 04 35 0a 0f` in the capture).

## 10. Follow-ups for the integration

1. Use the full type list (§2) for `DEVICE_TYPE_NAMES` and fix Fan / Relay 3 in SPECIFICATION.md §5.
2. Keep lights off 240–255:
   - `next_free_address()` in `hub.py`
   - number max in `number.py`
   - manual add in `config_flow.py`
3. Clamp brightness to at least 5 (`_level()` in `light.py`).
4. Once group layouts are known, offer real groups (temp group 253 or fixed groups) instead of shared mesh addresses.
5. Telling the phone app apart from lights (flags `1a` vs `02`) isn't possible with HA's `BluetoothServiceInfo` (no flags). Only the debug tool sees raw advertisements.
