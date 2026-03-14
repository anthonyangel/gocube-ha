# GoCube BLE Reconnect Bugs & Fix Plan

## Reference Integrations

- **Oral-B** (`oralb`): Passive BLE, battery-powered toothbrush — demonstrates sleepy-device availability pattern
- **Yale BLE** (`yalexs_ble`): Active GATT, battery-powered lock — best architectural match for GoCube

The GoCube requires an active GATT connection (Nordic UART Service) for bidirectional
communication. It cannot use passive advertisement scanning like Oral-B. The Yale lock
integration is the correct pattern to follow.

---

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

## Fix Plan: Implementation Order

### Phase 1: Critical connection fixes (Bugs 1, 2, 3, 7, 10, 12)

Rewrite the connection lifecycle:

1. **Pass `hass` into `GoCubeConnection`** so it can use HA Bluetooth APIs
2. **Store device address** separately from `BLEDevice` (Bug 2)
3. **Remove `_find_device` / raw `BleakScanner`** (Bug 7)
4. **Use `async_ble_device_from_address`** to get fresh device on connect (Bug 3, 10)
5. **Register disconnect callback** on `BleakClient` (Bug 1)
6. **Raise `ConfigEntryNotReady`** when cube unavailable at startup (Bug 12)
7. **Register `async_track_unavailable`** to detect cube going to sleep
8. **Register `async_register_callback`** to detect cube waking up

### Phase 2: Task management fixes (Bugs 4, 5, 6)

1. **Track all background tasks** in a set, cancel on unload (Bug 4)
2. **Use `hass.loop.call_soon_threadsafe`** in notification handler (Bug 5)
3. **Serialize reconnect** — single `_reconnect_task`, cancel-before-start (Bug 6)

### Phase 3: Entity availability fixes (Bugs 8, 9, 11)

1. **Expose `is_connected` property** on connection, remove private access (Bug 8)
2. **Don't reset parser on disconnect** — preserve last known state (Bug 11)
3. **Change entity availability model** — always available once seen,
   use `assumed_state` when disconnected (Bug 9)

### Phase 4: Minor fixes (Bug 13)

1. **Fix auto-reconnect switch** — toggle flag, don't disconnect (Bug 13)
