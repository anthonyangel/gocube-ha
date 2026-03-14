# GoCube HA Integration — Bugs, Architecture & Feature Plan

## Reference Integrations

- **Oral-B** (`oralb`): Passive BLE, battery-powered toothbrush — demonstrates sleepy-device availability pattern
- **Yale BLE** (`yalexs_ble`): Active GATT, battery-powered lock — best architectural match for GoCube

The GoCube requires an active GATT connection (Nordic UART Service) for bidirectional
communication. It cannot use passive advertisement scanning like Oral-B. The Yale lock
integration is the correct pattern to follow.

---

# Part 1: Bugs

## Bug 1: Disconnect callback never registered (CRITICAL)

**File:** `gocube_ble/connection.py:138`

`_handle_disconnect` is defined at line 202 but never passed to `BleakClient`:

```python
# Current (line 138)
self._client = BleakClient(device, timeout=CONNECT_TIMEOUT)

# Fixed
self._client = BleakClient(
    device,
    timeout=CONNECT_TIMEOUT,
    disconnected_callback=self._handle_disconnect,
)
```

**Impact:** Auto-reconnect never fires. When the cube sleeps or goes out of range, the
integration silently goes stale. All entities show old values without ever going
unavailable or attempting to reconnect.

**Fix:** Pass `disconnected_callback=self._handle_disconnect` to `BleakClient()`.

---

## Bug 2: `_cleanup_connection` clears `_device`, breaking reconnect

**File:** `gocube_ble/connection.py:120`

```python
# _cleanup_connection sets self._device = None (line 120)
# But _auto_reconnect checks self._device (line 215):
if not self._should_auto_reconnect or not self._device:
    return  # ← always returns because _device is None
```

The flow is: disconnect → `_handle_disconnect` → `_auto_reconnect` → `connect()` →
`_cleanup_connection()` → `self._device = None` → reconnect gives up.

**Fix:** Store the device address separately (`self._address`) and never clear it.
Use the address to get a fresh `BLEDevice` from HA's Bluetooth manager on reconnect
(which also fixes Bug 3).

---

## Bug 3: Stale `BLEDevice` reused on reconnect

**File:** `gocube_ble/connection.py:225`

```python
await self.connect(self._device)  # reuses the original BLEDevice object
```

After a device sleeps and wakes, the `BLEDevice` object from the original scan is
stale — its internal adapter reference, RSSI, and connection parameters may be invalid.

Yale BLE uses `async_ble_device_from_address()` to get a fresh device reference:

```python
from homeassistant.components.bluetooth import async_ble_device_from_address
device = async_ble_device_from_address(hass, address, connectable=True)
```

**Fix:** On reconnect, use `async_ble_device_from_address()` instead of the cached
`BLEDevice`. This requires passing `hass` into `GoCubeConnection` (see Fix Plan below).

---

## Bug 4: Untracked `asyncio.create_task` — leaks, races, silently lost

**Files:**
- `gocube_ble/connection.py:209` — `asyncio.create_task(self._auto_reconnect())`
- `gocube_ble/connection.py:300` — `asyncio.create_task(self._send_debounced_state_update())`
- `gocube_ble/connection.py:333` — `asyncio.create_task(self.send_command("GetState"))`

These fire-and-forget tasks:
1. Are never stored → can be garbage collected before completion
2. Cannot be cancelled on disconnect or HA unload
3. Can overlap (multiple reconnect tasks racing each other)
4. Swallow exceptions silently ("Task exception was never retrieved")

**Fix:** Track all tasks in a set. Cancel them on disconnect/unload.

```python
self._background_tasks: set[asyncio.Task] = set()

def _create_task(self, coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task
```

For reconnect specifically, store a single `_reconnect_task` and cancel any existing
one before starting a new one.

---

## Bug 5: `asyncio.create_task` called from Bleak callback thread

**File:** `gocube_ble/connection.py:333`

```python
def _notification_handler(self, sender: int, data: bytearray) -> None:
    # ...
    asyncio.create_task(self.send_command("GetState"))  # line 333
```

Bleak calls notification handlers from a background thread, not the HA event loop.
`asyncio.create_task()` only works from the event loop thread. From another thread,
it either silently fails or raises.

**Fix:** Use `hass.loop.call_soon_threadsafe()` or (better)
`hass.async_create_task()`, or schedule with `asyncio.run_coroutine_threadsafe()`:

```python
self._hass.loop.call_soon_threadsafe(
    self._hass.async_create_task,
    self.send_command("GetState"),
)
```

---

## Bug 6: Reconnect deadlock with `_connection_lock`

**File:** `gocube_ble/connection.py:130, 213`

`connect()` acquires `_connection_lock` (line 130). `_handle_disconnect` can fire at
any time and calls `_auto_reconnect()` which calls `connect()` which tries to acquire
the same lock.

`asyncio.Lock` is **not reentrant**. If disconnect fires while `connect()` holds the
lock (e.g., during a retry), `_auto_reconnect` will block forever waiting for the lock.

**Fix:** Don't call `connect()` directly from `_auto_reconnect()`. Instead, schedule
reconnect as a separate task that waits for any in-progress connection attempt to
finish. Or use a flag + event pattern instead of a lock.

---

## Bug 7: Raw `BleakScanner` bypasses HA's Bluetooth manager

**File:** `gocube_ble/connection.py:88`

```python
scanner = BleakScanner()
devices = await scanner.discover(timeout=SCAN_TIMEOUT)
```

Home Assistant manages Bluetooth adapters centrally. Using raw `BleakScanner`:
- Can conflict with HA's own scanner (adapter contention)
- Won't work with Bluetooth proxies (ESPHome BLE proxies)
- Doesn't benefit from HA's device tracking and caching
- May fail on multi-adapter systems

**Fix:** Remove `_find_device()` entirely. Use HA Bluetooth APIs:

```python
from homeassistant.components.bluetooth import async_ble_device_from_address
device = async_ble_device_from_address(hass, address, connectable=True)
```

---

## Bug 8: Entity availability reaches into private state (race condition)

**Files:** `sensor.py:118-122`, `binary_sensor.py:134-140`, `light.py:104-110`

All entities check:
```python
@property
def available(self) -> bool:
    return (
        self.connection._is_connected
        and self.connection._client is not None
        and self.connection._client.is_connected  # ← Bleak can change this from another thread
    )
```

Problems:
- Accesses private attributes (`_is_connected`, `_client`)
- `_client.is_connected` can change mid-evaluation from a Bleak background thread
- Three checks that can be inconsistent with each other

**Fix:** Expose a single `@property is_connected` on `GoCubeConnection` and use that:

```python
# In GoCubeConnection
@property
def is_connected(self) -> bool:
    return self._is_connected

# In entities
@property
def available(self) -> bool:
    return self.connection.is_connected
```

---

## Bug 9: Entities go unavailable when cube sleeps (bad UX)

**Files:** `sensor.py:116-122`, `binary_sensor.py:134-140`, `light.py:104-110`

The cube is battery-powered and sleeps most of the time. Current behavior:
- Entity shows "Unavailable" whenever cube is asleep
- Dashboard is filled with unavailable entities
- Last known values (battery, solved state) disappear from UI
- Automations based on entity state break
- History graphs have gaps

The Oral-B integration (also a sleepy battery device) uses this pattern:

```python
@property
def available(self) -> bool:
    return True  # once seen, always available

@property
def assumed_state(self) -> bool:
    return not self.processor.available  # shows data is stale
```

**Fix:** Once the cube has been seen at least once, return `available=True` always.
Use `assumed_state=True` when disconnected to indicate values are cached. The
`native_value` should return the last known value, not `None`.

---

## Bug 10: `__init__.py` passes address string to `connect()`, not `BLEDevice`

**File:** `__init__.py:33`

```python
await connection.connect(entry.data["address"])  # passes a string
```

But `connect()` signature expects `BLEDevice`:

```python
async def connect(self, device: BLEDevice) -> None:
```

This either fails immediately or relies on `connect()` internally calling
`_find_device()` (the raw BleakScanner from Bug 7). The `__init__.py` should use
HA's Bluetooth API to get a proper `BLEDevice` first.

**Fix:**

```python
from homeassistant.components.bluetooth import async_ble_device_from_address

device = async_ble_device_from_address(hass, entry.data["address"], connectable=True)
if device is None:
    raise ConfigEntryNotReady("GoCube not found")
await connection.connect(device)
```

---

## Bug 11: `_data_parser` reset on disconnect destroys state

**File:** `gocube_ble/connection.py:122`

```python
self._data_parser = GoCubeDataParser()  # creates new empty parser
```

On every disconnect (including sleep), the parser is replaced with a fresh instance.
This means:
- Battery level → `None`
- Face states → empty dict
- Solved state → `False`
- All last-known values are destroyed

Combined with Bug 9, the entities go unavailable AND lose their values.

**Fix:** Don't reset the parser on disconnect. The parser holds the last known state
and should persist across connection cycles.

---

## Bug 12: `async_setup_entry` returns `False` on connection failure

**File:** `__init__.py:38-39`

```python
except Exception as err:
    _LOGGER.error("Failed to connect to GoCube: %s", err)
    return False
```

Returning `False` means HA marks the integration as failed and won't retry. For a
battery-powered device that may be asleep at HA startup, this is wrong.

**Fix:** Raise `ConfigEntryNotReady` instead, which tells HA to retry setup later:

```python
from homeassistant.exceptions import ConfigEntryNotReady

except Exception as err:
    raise ConfigEntryNotReady(f"GoCube not available: {err}") from err
```

---

## Bug 13: `switch.py` auto-reconnect toggle calls `disconnect()` to turn off

**File:** `switch.py:89`

```python
async def async_turn_off(self, **kwargs: Any) -> None:
    if self.entity_description.key == "auto_reconnect":
        await self.connection.disconnect()  # disconnects AND disables auto-reconnect
```

Turning off "auto reconnect" shouldn't disconnect the cube — it should just stop
reconnecting when the cube naturally disconnects.

**Fix:** Set the flag without disconnecting:

```python
self.connection.should_auto_reconnect = False
```

---

# Part 2: Architectural Changes

## Adopt Yale BLE Lock Pattern

The current architecture is "persistent connection with auto-reconnect loop". The
correct HA pattern for a battery-powered active-GATT device is
**advertisement-triggered on-demand connection**.

### Current (broken)

```
HA starts → scan for device → connect → hold connection open forever
  → device sleeps → ??? (disconnect callback never registered)
  → device wakes → ??? (no mechanism to detect this)
```

### Target (Yale BLE pattern)

```
HA starts → register advertisement callback → wait
  → cube wakes → HA scanner sees advertisement → callback fires
  → get fresh BLEDevice → connect → start_notify → receive data
  → cube sleeps → async_track_unavailable fires → mark assumed_state
  → entities stay available with last known values
```

### Key HA Bluetooth APIs to use

```python
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,    # get fresh BLEDevice by address
    async_register_callback,          # detect cube waking up (advertisement seen)
    async_track_unavailable,          # detect cube going to sleep (no advertisement)
)
```

### Connection lifecycle in `__init__.py`

```python
async def async_setup_entry(hass, entry):
    address = entry.data["address"]
    connection = GoCubeConnection(hass, address)

    # Try to connect now (may fail if cube is asleep — that's OK)
    device = async_ble_device_from_address(hass, address, connectable=True)
    if device:
        await connection.connect(device)

    # Register for advertisement callbacks (cube waking up)
    entry.async_on_unload(
        async_register_callback(
            hass, connection.handle_advertisement,
            BluetoothCallbackMatcher(address=address),
        )
    )

    # Register for unavailability tracking (cube going to sleep)
    entry.async_on_unload(
        async_track_unavailable(
            hass, connection.handle_unavailable, address, connectable=True,
        )
    )

    # Set up platforms — entities created even if cube is asleep
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"connection": connection}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```

### Sleepy device entity model

All entities should follow the Oral-B pattern:

```python
@property
def available(self) -> bool:
    return self._has_been_seen  # True once we've received any data

@property
def assumed_state(self) -> bool:
    return not self.connection.is_connected  # stale data indicator

@property
def native_value(self):
    return self._last_known_value  # never return None just because disconnected
```

---

# Part 3: Library Separation

## Current structure (conceptually correct, needs cleanup)

```
custom_components/gocube/
├── gocube_ble/          ← self-contained library package
│   ├── ble.py           ← clean public API with __all__
│   ├── connection.py    ← BLE connection management
│   ├── const.py         ← protocol constants
│   ├── models.py        ← data models
│   └── parser.py        ← message parsing
├── __init__.py          ← HA integration
├── sensor.py
└── ...
```

## What needs to change

### Separate concerns into three layers

| Layer | Responsibility | Where it lives |
|---|---|---|
| **Protocol** | Constants, message parsing, frame validation | `gocube-ble` PyPI package |
| **Connection** | Thin Bleak wrapper: connect, send, notify | `gocube-ble` PyPI package |
| **Policy** | Reconnect, debouncing, retry, HA lifecycle | HA integration (`__init__.py`) |

### Currently mixed in `connection.py`

These belong in the **HA integration**, not the library:
- `_auto_reconnect()` — reconnect policy
- `_send_debounced_state_update()` — debounce policy
- `_should_auto_reconnect` — HA-specific flag
- `enable_auto_reconnect()` — HA-specific method
- `_find_device()` — scanner policy (should use HA Bluetooth APIs)

### Target library API

```python
# gocube-ble PyPI package — thin, no HA dependencies
class GoCubeConnection:
    async def connect(self, device: BLEDevice) -> None
    async def disconnect(self) -> None
    async def send_command(self, command: str) -> None
    def register_callback(self, callback) -> Callable
    @property
    def is_connected(self) -> bool
    @property
    def data(self) -> GoCubeData
```

No scanning, no reconnect, no debouncing — the HA integration owns all of that.

### Target structure

```
# PyPI package: gocube-ble
gocube_ble/
├── __init__.py          ← public API
├── const.py             ← protocol constants + commands
├── models.py            ← GoCubeData, orientation quaternion, stats
├── parser.py            ← message framing, validation, parsing
├── connection.py        ← thin Bleak wrapper: connect, send, notify
└── renderer.py          ← isometric cube renderer (for camera entity)

# HA integration: custom_components/gocube
custom_components/gocube/
├── __init__.py          ← coordinator, reconnect policy, BLE lifecycle
├── camera.py            ← ImageEntity using renderer
├── sensor.py
├── binary_sensor.py
├── event.py             ← rotation + orientation events
├── light.py
├── button.py
├── switch.py
├── config_flow.py
└── manifest.json        ← requirements: ["gocube-ble>=2.0.0"]
```

---

# Part 4: Feature-Complete BLE Protocol

## Currently implemented

| Message | Type | Status |
|---|---|---|
| `MsgRotation` | `0x01` | Implemented — fires rotation events |
| `MsgState` | `0x02` | Implemented — parses 54 sticker colors, face solved state |
| `MsgOrientation` | `0x03` | **Stub** — parsed but discarded (`parser.py:66`) |
| `MsgBattery` | `0x05` | Implemented — battery percentage |
| `MsgStats` | `0x07` | **Not implemented** — constant defined but not parsed |
| `MsgCubeType` | `0x08` | **Not implemented** — constant defined but not parsed |

## Commands currently implemented

| Command | Byte | Status |
|---|---|---|
| `GetBattery` | `0x32` | Used |
| `GetState` | `0x33` | Used |
| `Reboot` | `0x34` | Used (button entity) |
| `SetSolvedState` | `0x35` | Defined, not exposed |
| `DisableOrientation` | `0x37` | Used on connect |
| `EnableOrientation` | `0x38` | Defined, not used |
| `GetStats` | `0x39` | Defined, not used |
| `GetCubeType` | `0x56` | Defined, not used |
| LED commands | `0x41-0x44` | Used (light entity) |

## What needs to be added

### 1. Orientation quaternion parsing (`MsgOrientation` 0x03)

Currently a no-op in `parser.py:66`:
```python
def parse_orientation_message(self, data: bytearray) -> None:
    if len(data) >= 5:
        _LOGGER.debug("Received orientation update")  # ← does nothing
```

Needs to parse quaternion (x, y, z, w) from the message payload and store it in
`GoCubeData`. The GoCube app uses this at 15fps to rotate the 3D cube in real-time.

Add to `models.py`:
```python
@dataclass
class Orientation:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

@dataclass
class GoCubeData:
    # ... existing fields ...
    orientation: Orientation | None = None
```

### 2. Stats message parsing (`MsgStats` 0x07)

Parse session statistics from the cube: solve count, total time, etc.
Expose as diagnostic sensor entities.

### 3. Cube type detection (`MsgCubeType` 0x08)

Parse the cube model/hardware version. Store in `GoCubeData.cube_type`.
Use in device info for the HA device registry.

### 4. Multi-rotation support

The current rotation handler only reads a single rotation from byte 3:
```python
face_rotation = data[3]
```

Some protocol messages contain multiple sequential rotations in a single notification.
Parser should handle variable-length rotation payloads.

### 5. Message framing and validation

Currently no validation of message framing. The protocol uses:
- Prefix: `0x2A` (`MSG_PREFIX` — defined but not checked)
- Suffix: `0x0D 0x0A` (CR LF — `MSG_SUFFIX` — defined but not checked)

Parser should validate frame boundaries and checksums before processing.

---

# Part 5: Cube Visualization

## Tier 1: Static Isometric ImageEntity (quick win)

Generate a SVG or PNG showing 3 visible faces of the cube from a fixed isometric
angle. Updates on every move via `MsgState`.

**What's needed:**
- `renderer.py` in the gocube-ble library — takes 54 sticker colors, produces image
- `camera.py` in the HA integration — `ImageEntity` that serves the rendered image
- No orientation data needed — fixed camera angle
- No frontend/JavaScript work — pure backend Python

**Data already available:** The 54 sticker colors from `MsgState` (already parsed
and stored in `GoCubeData.face_states`). Currently stored as per-face solved/unsolved
booleans — needs to be extended to store actual per-sticker colors for rendering.

### Changes to models.py

```python
@dataclass
class GoCubeData:
    battery_level: int | None = None
    is_solved: bool = False
    face_states: dict[str, bool] = None          # existing: per-face solved
    face_colors: list[list[int]] = None           # new: 6 faces x 9 stickers
    orientation: Orientation | None = None         # new: quaternion
    # ...
```

### Renderer approach

Isometric projection of a Rubik's cube showing top, right, and front faces (3 of 6).
Each face is a 3x3 grid of colored squares with slight perspective transform.

Options:
- **SVG** — scalable, clean, small file size, easy to generate
- **Pillow/PNG** — raster, more control over anti-aliasing

SVG is the better choice for HA dashboards (scales to any card size).

## Tier 2: Live 3D Rotating Cube (custom Lovelace card)

A custom frontend card using three.js / WebGL that renders a textured 3D cube
rotating in real-time based on orientation data from the cube.

**Architecture:**
```
GoCube (BLE)
  → MsgOrientation @ 15fps → HA event entity
  → MsgState on moves      → HA sensor entity
      ↓
Custom Lovelace Card (three.js)
  → subscribes to orientation events via WebSocket
  → subscribes to state entity for face colors
  → renders textured 3D cube, rotating in real-time
```

**Challenges:**
- HA's entity update loop isn't designed for 15fps streaming
- Options: event entity (fires events, card subscribes via WebSocket), or expose a
  WebSocket API directly, or throttle to ~5fps
- This is a separate frontend project (JavaScript/TypeScript, npm build pipeline)
- Would need HACS frontend distribution

**Effort:** Significant — separate JS project. The isometric ImageEntity (Tier 1)
is the prerequisite and quick win.

---

# Part 6: Implementation Order

## Phase 1: Fix critical bugs + adopt Yale BLE pattern

**Goal:** Working, reliable BLE connection for a battery-powered device.

1. Pass `hass` into `GoCubeConnection` (enables HA Bluetooth APIs)
2. Store device address separately, never clear it (Bug 2)
3. Remove `_find_device` / raw `BleakScanner` (Bug 7)
4. Use `async_ble_device_from_address` for fresh device on connect (Bug 3, 10)
5. Register disconnect callback on `BleakClient` (Bug 1)
6. Raise `ConfigEntryNotReady` when cube unavailable at startup (Bug 12)
7. Register `async_track_unavailable` for sleep detection
8. Register `async_register_callback` for wake detection
9. Don't reset parser on disconnect (Bug 11)

## Phase 2: Fix task management + entity UX

**Goal:** No more leaked tasks, races, or deadlocks. Clean dashboard UX.

1. Track all background tasks in a set, cancel on unload (Bug 4)
2. Use `hass.loop.call_soon_threadsafe` in notification handler (Bug 5)
3. Serialize reconnect — single task, cancel-before-start (Bug 6)
4. Expose `is_connected` property, remove private attribute access (Bug 8)
5. Sleepy device availability model — always available, `assumed_state` (Bug 9)
6. Fix auto-reconnect switch — toggle flag, don't disconnect (Bug 13)

## Phase 3: Library separation

**Goal:** Clean PyPI-publishable library with no HA dependencies.

1. Move reconnect/retry/debounce policy out of `gocube_ble/connection.py` into `__init__.py`
2. Keep `gocube_ble` as thin Bleak wrapper + protocol parser
3. Add proper message framing/validation to parser
4. Set up PyPI package structure and publish
5. Update `manifest.json` to reference `gocube-ble` from PyPI

## Phase 4: Feature-complete BLE protocol

**Goal:** Parse and expose all GoCube protocol messages.

1. Implement orientation quaternion parsing (`MsgOrientation` 0x03)
2. Implement stats message parsing (`MsgStats` 0x07)
3. Implement cube type detection (`MsgCubeType` 0x08)
4. Handle multi-rotation payloads
5. Add frame validation (prefix/suffix/checksum)
6. Extend `GoCubeData` model with orientation, stats, per-sticker colors
7. Add new sensor/diagnostic entities for stats and cube type

## Phase 5: Cube visualization — Tier 1 (isometric image)

**Goal:** Visual cube state on the HA dashboard.

1. Extend parser to store per-sticker colors (not just per-face solved boolean)
2. Implement `renderer.py` — isometric SVG generator
3. Implement `camera.py` — `ImageEntity` serving rendered cube
4. Updates on every `MsgState`

## Phase 6: Cube visualization — Tier 2 (live 3D card)

**Goal:** App-like real-time 3D cube in the browser.

1. Enable orientation streaming (`EnableOrientation` command)
2. Expose orientation as event entity (or WebSocket API)
3. Build custom Lovelace card (three.js, TypeScript)
4. Subscribe to orientation events + state via WebSocket
5. Render textured 3D cube rotating in real-time
6. Package for HACS frontend distribution
