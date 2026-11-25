# Mic Level Light

Release tier: small (tags `v1.0`, `v1.1` ...; `VERSION` in `mic_level_light.py` is the same number and the Debian version).
Single file. Calm UI by request (2026-11-25): no flashing words or colours; level bar, gain slider, 30 s test. Only the slider writes
anything (`pactl set-source-volume`). Analog gain mapping and profiles belong in ASR-Mic-Tuner. A tag builds the .deb in
`.github/workflows/release.yml`; do not build locally. Tests: `tests/`, synthetic audio. Thresholds: constants at the
top of the script and the README table, changed together (band matches ASR-Training `take_levels.py`).
