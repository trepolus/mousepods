# MousePods: notes for coding agents

AirPods head tracking as a mouse. Linux reads the AirPods directly over L2CAP (BlueZ) and moves the cursor with
uinput; macOS reads Apple's CoreMotion headphone API through a Swift helper and moves the cursor with CoreGraphics.
Background and protocol findings: `README.md`, `llms.txt`, `docs/`.

## Commands

```bash
python3 -m unittest discover -s tests            # all Python tests, no hardware needed
uv run --project . mousepods --help              # run from anywhere with uv (pyproject.toml)
macos/build.sh                                   # macOS helper: swift test, build, .app bundle, ad-hoc sign
(cd macos && swift test)                         # Swift tests only
```

On macOS two tests fail for platform reasons (no `SOCK_SEQPACKET` in `test_l2cap`, `/private/var` paths in
`test_steam_games`); they pass on Linux.

## Layout

| Path | Role |
|---|---|
| `airpods_mouse_controller.py` | controller: engine, modes, clicks, `run()` (Linux loop) and `run_macos()` |
| `Controller.on_sample` | source-independent entry for one motion sample; `on_block` decodes the raw AirPods block |
| `macos/` | Swift package: `MotionWire` (pure wire types) and the `mousepods-motion` helper app |
| `macos_motion.py` | macOS motion source: helper datagrams, unit conversion, CoreMotion profile, guided recorder |
| `macos_pointer.py` | macOS cursor: pure cursor maths plus a thin ctypes CoreGraphics adapter |
| `captures/` | real recordings replayed by tests; `captures/private/` is git-ignored |

## Pitfalls

- macOS only grants Motion & Fitness to an app bundle with `NSMotionUsageDescription`; a bare binary started from a
  terminal is attributed to the terminal and killed. The helper ships as a `.app` and is started with `open`.
- Swift 6: closures written in `main.swift` top-level code are main-actor isolated; CoreMotion and Carbon call
  back on other threads, so build such handlers in functions (see `makeMotionHandler`).
- `tests/test_glide_calib.py` swaps the global `time.monotonic`; inject a clock instead of reading the real one in
  loops under test, or the full suite can hang.
- Every top-level module and package must be listed in `pyproject.toml` (`tests/test_pyproject.py` checks it).
- ctypes cannot call variadic C functions safely on Apple silicon: use `CGEventCreateScrollWheelEvent2`.
- The helper/controller wire format is mirrored in `macos/Sources/MotionWire` and `macos_motion.py`; change both
  and their contract tests together.

## Conventions

- Pure decision logic separate from I/O adapters; table-driven tests; real captures as fixtures.
- New code, logs and docs in English (older code and logs are partly French).
- Small atomic commits with an imperative summary.
