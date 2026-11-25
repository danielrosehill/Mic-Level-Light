#!/usr/bin/python3
"""Mic Level Light: a calm microphone level bar, a gain slider and a 30-second test."""
import json, subprocess, sys
from collections import deque
import numpy as np

VERSION = "1.1"
RATE, BLOCK = 48000, 2400            # 50 ms blocks
LOW, HIGH = -26.0, -14.0             # ASR sweet spot: speech RMS, dBFS (100 Hz and up)
TARGET, HOT_PEAK, CLIP = -20.0, -1.5, 0.999
TEST_SECONDS = 30


def db(v):
    return 20 * np.log10(max(float(v), 1e-6))


def active(rms):
    """Mask of the blocks that stand above the background (speech)."""
    rms = np.asarray(rms)
    floor = np.percentile(rms, 10)
    return rms > min(max(-55.0, floor + 8), -30.0)


def mean_db(levels):
    return float(10 * np.log10(np.mean(10 ** (np.asarray(levels) / 10))))


class Analyser:
    """Feed 50 ms blocks shaped (samples, channels); the loudest channel decides."""
    def __init__(self):
        self.win = np.hanning(BLOCK)
        self.keep = np.fft.rfftfreq(BLOCK, 1 / RATE) >= 100
        self.hist = deque(maxlen=200)        # 10 s, for the live average
        self.test = None                     # list while a test runs
        self.last_clip, self.n = -10**9, 0
        self.shown = -120.0                  # slow level for the bar

    def feed(self, x):
        peak = float(np.abs(x).max())
        clipped = int((np.abs(x) >= CLIP).sum())
        spec = np.abs(np.fft.rfft(x * self.win[:, None], axis=0)) ** 2
        # Parseval, one-sided, undoing the window power: RMS without rumble below 100 Hz
        ms = 2 * spec[self.keep].sum(axis=0) / (BLOCK * (self.win ** 2).sum())
        row = (db(np.sqrt(ms.max())), db(peak), clipped)
        self.n += 1
        if clipped:
            self.last_clip = self.n
        self.hist.append(row)
        if self.test is not None:
            self.test.append(row)
        self.shown += (row[0] - self.shown) * (0.3 if row[0] > self.shown else 0.08)

    def clipping(self):
        return self.n - self.last_clip < 60  # held 3 s

    def live_average(self):
        """Average speech level of the last 10 s, None without about 1 s of speech."""
        rms = [r for r, _, _ in self.hist]
        if len(rms) < 20:
            return None
        m = active(rms)
        return mean_db(np.asarray(rms)[m]) if m.sum() >= 20 else None


def summarise(rows):
    """Averages and one recommendation for a finished test."""
    rms, peaks = np.array([r[0] for r in rows]), np.array([r[1] for r in rows])
    m = active(rms)
    out = dict(seconds=len(rows) / 20, speech_seconds=float(m.sum() / 20), peak=float(peaks.max()),
               clipped=sum(r[2] for r in rows), speech=None, background=None, change=0)
    if m.sum() < 60:                         # under 3 s of speech
        out["verdict"] = "Not enough speech to judge. Read aloud for the whole test."
        return out
    out["speech"] = mean_db(rms[m])
    out["background"] = float(np.median(rms[~m])) if (~m).any() else None
    sp = out["speech"]
    if out["clipped"]:
        out["change"] = -max(6, round(sp - TARGET))
        out["verdict"] = f"Clipping: lower the gain by about {-out['change']} dB, then test again."
    elif sp > HIGH or out["peak"] > HOT_PEAK:
        out["change"] = -max(3, round(sp - TARGET))
        out["verdict"] = f"Too loud: lower the gain by about {-out['change']} dB."
    elif sp < LOW:
        out["change"] = max(0, min(round(TARGET - sp), int(-3 - out["peak"])))
        out["verdict"] = (f"Too quiet: raise the gain by about {out['change']} dB, or move closer." if out["change"]
                          else "Too quiet on average, but the peaks leave no room for more gain. Move closer.")
    else:
        out["verdict"] = "In the sweet spot. Leave it there."
    return out


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def sources():
    try:
        rows = json.loads(run("pactl", "-f", "json", "list", "sources") or "[]")
    except ValueError:
        return {}
    out = {}
    for s in rows:
        if s["name"].endswith(".monitor") or s.get("properties", {}).get("device.class") == "monitor":
            continue
        vols = list(s.get("volume", {}).values())
        out[s["name"]] = dict(label=s.get("description") or s["name"], mute=s.get("mute", False),
                              gain=int(vols[0]["value_percent"].rstrip("%")) if vols else 0,
                              gain_db=vols[0].get("db", "") if vols else "",
                              ch=max(1, len(s.get("channel_map", "mono").split(","))))
    return out


def main():
    from PyQt6.QtCore import QProcess, QRectF, Qt, QTimer
    from PyQt6.QtGui import QColor, QIcon, QPainter
    from PyQt6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QProgressBar,
                                 QPushButton, QSlider, QVBoxLayout, QWidget)

    class Meter(QWidget):
        LO = -60.0

        def __init__(self):
            super().__init__()
            self.level, self.avg = -120.0, None
            self.setFixedHeight(96)

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pal, w, top, h = self.palette(), self.width(), 24, 42
            x = lambda v: w * min(1, max(0, (v - self.LO) / -self.LO))
            p.fillRect(QRectF(0, top, w, h), pal.mid())
            p.fillRect(QRectF(x(LOW), top, x(HIGH) - x(LOW), h), QColor(46, 125, 50, 150))
            p.fillRect(QRectF(0, top + 14, x(self.level), h - 28), pal.highlight())
            p.setPen(pal.windowText().color())
            mid = Qt.AlignmentFlag.AlignCenter
            p.drawText(QRectF(x(LOW) - 40, 0, x(HIGH) - x(LOW) + 80, 22), mid, "ASR sweet spot")
            for v in (-50, -40, -26, -14, -6):
                p.drawText(QRectF(x(v) - 25, top + h + 4, 50, 22), mid, str(v))
            if self.avg is not None:         # average of the last 10 s of speech
                p.fillRect(QRectF(x(self.avg) - 2, top - 3, 4, h + 6), pal.windowText())

    class Window(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Mic Level Light")
            self.resize(560, 420)
            self.pick, self.meter = QComboBox(), Meter()
            self.gain = QSlider(Qt.Orientation.Horizontal)
            self.gain.setRange(0, 100); self.gain.setSingleStep(1); self.gain.setPageStep(5)
            self.gain_text, self.live = QLabel(), QLabel()
            self.gain_text.setMinimumWidth(130)
            self.button, self.bar = QPushButton(f"Record a {TEST_SECONDS}-second test"), QProgressBar()
            self.bar.setRange(0, TEST_SECONDS * 20); self.bar.setTextVisible(False)
            self.result = QLabel("Read aloud normally during the test.")
            self.result.setWordWrap(True); self.result.setMinimumHeight(120)
            self.result.setAlignment(Qt.AlignmentFlag.AlignTop)
            row = QHBoxLayout(); row.addWidget(self.gain, 1); row.addWidget(self.gain_text)
            form = QFormLayout(); form.addRow("Microphone", self.pick); form.addRow("Gain", row)
            box = QVBoxLayout(self)
            box.addLayout(form); box.addSpacing(8)
            for w in (self.meter, self.live, self.button, self.bar, self.result):
                box.addWidget(w)
            box.addStretch(1)
            self.proc, self.buf, self.cur, self.ch, self.src = None, b"", None, 1, {}
            self.an, self.start_gain, self.gain_moved = Analyser(), None, False
            self.gain_timer = QTimer(self); self.gain_timer.setSingleShot(True); self.gain_timer.setInterval(120)
            self.gain_timer.timeout.connect(self.set_gain)
            self.gain.valueChanged.connect(self.gain_changed)
            self.pick.currentIndexChanged.connect(self.poll)
            self.button.clicked.connect(self.toggle_test)
            self.poll()
            for ms, fn in ((1500, self.poll), (60, self.draw), (1000, self.text)):
                t = QTimer(self); t.timeout.connect(fn); t.start(ms)
            self.text()

        # gain
        def gain_changed(self, v):
            self.gain_text.setText(f"{v}%")
            self.gain_timer.start()

        def set_gain(self):
            if self.cur in self.src:
                run("pactl", "set-source-volume", self.cur, f"{self.gain.value()}%")
                self.poll()

        def show_gain(self):
            s = self.src.get(self.cur)
            testing = self.an.test is not None
            self.gain.setEnabled(bool(s) and not testing)
            if not s:
                self.gain_text.setText("–")
                return
            if testing and s["gain"] != self.start_gain:
                self.gain_moved = True
            if self.gain.isSliderDown() or self.gain_timer.isActive():
                return
            self.gain.blockSignals(True)
            self.gain.setValue(min(100, s["gain"]))
            self.gain.blockSignals(False)
            self.gain_text.setText(f"{s['gain']}%  {s['gain_db']}" + ("  MUTED" if s["mute"] else ""))

        # source
        def poll(self):
            self.src = sources()
            chosen = self.pick.currentData() or ""
            default = run("pactl", "get-default-source")
            label = self.src.get(default, {}).get("label", "none")
            want = [("", f"Default: {label}")] + [(n, s["label"]) for n, s in self.src.items()]
            have = [(self.pick.itemData(i), self.pick.itemText(i)) for i in range(self.pick.count())]
            if want != have:
                self.pick.blockSignals(True)
                self.pick.clear()
                for n, text in want:
                    self.pick.addItem(text, n)
                self.pick.setCurrentIndex(max(0, self.pick.findData(chosen)))
                self.pick.blockSignals(False)
                chosen = self.pick.currentData()
            name = chosen or default
            alive = self.proc and self.proc.state() != QProcess.ProcessState.NotRunning
            if name != self.cur or not alive:
                self.open(name)
            self.show_gain()

        def stop(self):
            if self.proc:
                self.proc.readyReadStandardOutput.disconnect()
                self.proc.kill(); self.proc.waitForFinished(500)
                self.proc.deleteLater()
                self.proc = None

        def open(self, name):
            if self.an.test is not None:
                self.end_test("Test stopped: the microphone changed.")
            self.stop()
            self.gain_timer.stop()           # never send a pending gain to a different mic
            self.cur, self.buf, self.an = name, b"", Analyser()
            if name not in self.src:
                return
            self.ch = self.src[name]["ch"]
            self.proc = QProcess(self)
            self.proc.readyReadStandardOutput.connect(self.read)
            self.proc.start("parec", ["-d", name, "--raw", "--format=float32le", f"--rate={RATE}",
                                      f"--channels={self.ch}", "--latency-msec=40",
                                      "--client-name=Mic Level Light"])

        def read(self):
            self.buf += bytes(self.proc.readAllStandardOutput())
            size = BLOCK * self.ch * 4
            while len(self.buf) >= size:
                self.an.feed(np.frombuffer(self.buf[:size], "<f4").reshape(-1, self.ch))
                self.buf = self.buf[size:]
                if self.an.test is not None and len(self.an.test) >= TEST_SECONDS * 20:
                    self.finish()

        # test
        def toggle_test(self):
            if self.an.test is not None:
                self.end_test("Test cancelled.")
            elif self.cur in self.src:
                self.start_gain, self.gain_moved, self.an.test = self.src[self.cur]["gain"], False, []
                self.button.setText("Cancel test")
                self.result.setText("Recording. Read aloud normally.")
                self.show_gain()

        def end_test(self, text):
            self.an.test = None
            self.bar.setValue(0)
            self.button.setText(f"Record a {TEST_SECONDS}-second test")
            self.result.setText(text)
            self.show_gain()

        def finish(self):
            r = summarise(self.an.test)
            if r["change"] > 0 and self.src.get(self.cur, {}).get("gain", 0) >= 100:
                r["verdict"] = (f"Too quiet by about {r['change']} dB, and the gain here is at its maximum. "
                                "Turn up the dial on the mic, or move closer.")
            f = lambda v: "–" if v is None else f"{v:.0f} dBFS"
            text = (f"<p><b>{r['verdict']}</b></p>Average speech: <b>{f(r['speech'])}</b> (sweet spot {LOW:.0f} to {HIGH:.0f})"
                    f"<br>Highest peak: {f(r['peak'])}<br>Clipped samples: {r['clipped']}"
                    f"<br>Background: {f(r['background'])}<br>Speech heard: {r['speech_seconds']:.0f} of {r['seconds']:.0f} s")
            if self.gain_moved:
                text += "<p>The gain changed during this test (another program moved it), so these averages mix two settings.</p>"
            self.end_test(text)

        # display
        def draw(self):
            self.meter.level, self.meter.avg = self.an.shown, self.avg
            self.meter.update()
            if self.an.test is not None:
                self.bar.setValue(len(self.an.test))

        def text(self):
            self.avg = self.an.live_average()
            t = "Speech average, last 10 s: " + ("–" if self.avg is None else f"{self.avg:.0f} dBFS")
            self.live.setText(t + ("      <b>clipped</b>" if self.an.clipping() else ""))

        avg = None

        def closeEvent(self, e):
            self.stop()
            e.accept()

    app = QApplication(sys.argv)
    app.setApplicationName("Mic Level Light")
    app.setDesktopFileName("mic-level-light")
    app.setWindowIcon(QIcon.fromTheme("audio-input-microphone"))
    win = Window()
    win.show()
    if "--screenshot" in sys.argv:       # used by docs and smoke tests
        path = sys.argv[sys.argv.index("--screenshot") + 1]
        QTimer.singleShot(4000, lambda: (win.grab().save(path), win.stop(), app.quit()))
    return app.exec()


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(VERSION)
    else:
        sys.exit(main())
