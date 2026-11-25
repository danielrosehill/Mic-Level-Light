# Mic Level Light

One big light for your microphone level on Debian and Ubuntu: **CLIPPING**, **TOO LOUD**, **GOOD** or **TOO LOW**. Set the gain by eye.

![Mic Level Light showing GOOD](docs/screenshot.png)

Install the `.deb` from [Releases](https://github.com/danielrosehill/Mic-Level-Light/releases): `sudo apt install ./mic-level-light_*_all.deb`. Needs PipeWire (with pipewire-pulse) or PulseAudio.

| Light | When |
|---|---|
| CLIPPING | any sample at full scale (0.999 or above), held for 2 s |
| TOO LOUD | peak above -1.5 dBFS in the last 3 s, or speech above -14 dBFS |
| GOOD | speech between -26 and -14 dBFS |
| TOO LOW | speech below -26 dBFS |
| SPEAK | no speech in the last 1.5 s |
| NO SIGNAL | muted, unplugged or digital silence |

"Speech" is the 80th percentile RMS of the 50 ms blocks in the last 3 s that stand above the background, counting only 100 Hz and up, so desk rumble cannot pass for voice. Peaks and clipping use the full signal. With several channels the loudest decides. The white line is peak hold.

It is read-only: it never changes gain or the default input. It shows the system gain, so you can see when something else moves it.

Limit: it sees the signal after the system volume. If the microphone clips in its own hardware and the volume is below 100%, the flattened peaks sit below full scale and are not flagged.

For analog gain control, noise measurement and per-mic profiles see [ASR Mic Tuner](https://github.com/danielrosehill/ASR-Mic-Tuner).
