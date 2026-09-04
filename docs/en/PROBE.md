# The SMU Probe (`acsprobe`) — Implementation Notes

What the external probe does and how, for maintainers and the curious. The
probe is a small single-file C# CLI (built on irusanov's ZenStates-Core
driver library) that exposes exactly the hardware access this project needs.
It ships with the toolchain — it is not part of this repository.

其他语言 / Other language: [中文版](../zh/PROBE.md)

---

## Commands this project uses

| Command | Purpose |
|---|---|
| `acsprobe cs-set <row> <col> <offset> -f` | stage one CurveShaper cell |
| `acsprobe cs-clear -f` | stage all 15 cells to 0 |
| `acsprobe read <smn-hex>` | read one SMN dword (Tctl temperature) |
| `acsprobe info` / `co-get` | environment self-check (CPU/SMU info, per-core CO readback) |

## CurveShaper write path

- **Interface**: ACPI AOD WMI namespace `root\wmi`, class `AMD_ACPI`,
  instance `ACPI\PNP0C14\AOD_0`. CurveShaper does not use any SMU mailbox.
- **Object**: `0x00020059` ("Set Curve Shaper"); accepted range −30…+30,
  step 1.
- **Frame**: `RunCommand(Inbuf[8])` — outer sequence
  `Start(0x00040001, 0)` → N × `{ObjectId u32 LE, Value u32 LE}` →
  `End(0x00040002, 0)`.
- **Value encoding**: `value = (idx << 8) | (offset & 0xFF)` with
  `idx = row*3 + col` (rows 0–4 = Min/Low/Mid/High/Max frequency points;
  columns 0–2 = cold/mid/hot temperature anchors), negative offsets in
  two's complement (−30 → 0xE2).
- **Semantics**: write-through *staging* — the BIOS pushes the staged grid
  into the SMU at the next POST. No runtime effect, and no readback
  (querying the object always returns 0): the applied state can only be
  inferred from behavior (frequency / VID changes) or vendor tooling.
  This is why every grid change costs one reboot.

## SMN read path (temperature)

- `acsprobe read 0x59800` returns the raw Tctl dword;
  `Tctl(°C) = (raw >> 21) * 0.125 − 49`.
- Access runs through the WinRing0/ZenStates-Core kernel driver, so the
  calling process must be elevated; otherwise the driver start fails
  (surfaced as `INIT-FAIL` / `TemperatureError`).
- One process per read ⇒ ~2.4 Hz max sampling rate, plenty for the
  per-window temperature statistics of the calibration battery.

## Per-core Curve Optimizer (not used by this tool)

`co-set` / `co-get` go through the RSMU mailbox (0x06 write / 0xD5 read),
are **per-core**, and take effect **immediately** — no reboot. A per-core
CO search without reboot cycles is a possible future stage; the current
pipeline is CurveShaper-only.

## Why an external CLI process?

The kernel driver has a lifecycle (install, start, stop) and hard elevation
requirements. Isolating it in a tiny stateless CLI keeps the GUI free of
driver-lifecycle code, makes the elevation boundary explicit, and lets the
Python side treat probe failures as ordinary subprocess errors
(`MeasurementError` / `TemperatureError`).

See also: [README.md](README.md) · [CALIBRATION.md](CALIBRATION.md)
