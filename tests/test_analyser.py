import numpy as np, pytest
from mic_level_light import Analyser, BLOCK, RATE, summarise

def play(rms_db, freq=300, secs=30, live=None):
    a = Analyser(); a.test = []; t = np.arange(BLOCK) / RATE
    for i in range(secs * 20):
        g = 10 ** (rms_db / 20) * 2 ** .5 if i % 10 < 6 else 1e-3
        x = np.tile((g * np.sin(2 * np.pi * freq * t))[:, None], (1, 2)).clip(-1, 1)
        if live is not None:
            x[:, 1 - live] = 0
        a.feed(x)
    return a

@pytest.mark.parametrize("lvl,word", [(-40, "Too quiet"), (-20, "sweet spot"), (-10, "Too loud"), (0, "Clipping")])
def test_verdict(lvl, word): assert word in summarise(play(lvl).test)["verdict"]
def test_calibration():
    a = play(-20); assert abs(summarise(a.test)["speech"] + 20) < .5 and abs(a.live_average() + 20) < .5
def test_change(): assert summarise(play(-30).test)["change"] == 10
def test_rumble_is_not_speech(): assert summarise(play(-20, freq=40).test)["speech"] is None
def test_rumble_can_clip(): assert summarise(play(0, freq=40).test)["clipped"] > 0
def test_silence(): assert summarise(play(-200).test)["speech"] is None
def test_one_live_channel(): assert "sweet" in summarise(play(-20, live=1).test)["verdict"]
