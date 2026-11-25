import numpy as np, pytest
from mic_level_light import Analyser, BLOCK, RATE

def play(rms_db, freq=300, secs=4, gap=True, ch=2, live=None):
    a = Analyser(); t = np.arange(BLOCK) / RATE
    for i in range(secs * 20):
        on = not gap or i % 10 < 6
        g = 10 ** (rms_db / 20) * 2 ** .5 if on else 1e-3
        x = np.tile((g * np.sin(2 * np.pi * freq * t))[:, None], (1, ch)).clip(-1, 1)
        if live is not None:
            x[:, 1 - live] = 0
        a.feed(x)
    return a

@pytest.mark.parametrize("lvl,want", [(-40, "low"), (-20, "good"), (-10, "hot"), (0, "clip")])
def test_levels(lvl, want): assert play(lvl).state() == want
def test_calibration():
    a = play(-20); a.state(); assert abs(a.speech_db + 20) < .5
def test_rumble_is_not_speech(): assert play(-20, freq=40).state() == "wait"
def test_rumble_can_clip(): assert play(0, freq=40).state() == "clip"
def test_silence(): assert play(-200, gap=False).state() == "dead"
def test_one_live_channel(): assert play(-20, live=1).state() == "good"
