#!/usr/bin/python3
"""Mic Level Light: one big light for the microphone level. Read-only; never changes gain."""
import json, subprocess, sys
from collections import deque
import numpy as np

VERSION = "1.0"
RATE, BLOCK = 48000, 2400            # 50 ms blocks
LOW, HIGH = -26.0, -14.0             # speech RMS band, dBFS (100 Hz and up)
HOT_PEAK, CLIP = -1.5, 0.999         # dBFS, sample magnitude
STATES = {                           # key: (word, hint, colour)
    "clip": ("CLIPPING", "Turn the gain down", "#c62828"),
    "hot":  ("TOO LOUD", "Turn the gain down a little", "#ef6c00"),
    "good": ("GOOD", "Leave it there", "#2e7d32"),
    "low":  ("TOO LOW", "Turn the gain up, or move closer", "#1565c0"),
    "wait": ("SPEAK", "Talk normally for a few seconds", "#424242"),
    "dead": ("NO SIGNAL", "Is the mic muted or unplugged?", "#212121"),
}


def db(v):
    return 20 * np.log10(max(float(v), 1e-6))


class Analyser:
    """Feed 50 ms blocks shaped (samples, channels); the loudest channel decides."""
    def __init__(self):
        self.win = np.hanning(BLOCK)
        self.keep = np.fft.rfftfreq(BLOCK, 1 / RATE) >= 100
        self.hist = deque(maxlen=200)        # 10 s of (rms_db, peak_db, clipped)
        self.last_clip = -10**9
        self.n = 0
        self.peak_db = self.rms_db = -120.0
        self.speech_db = None

    def feed(self, x):
        peaks = np.abs(x).max(axis=0)
        clipped = int((np.abs(x) >= CLIP).sum())
        spec = np.abs(np.fft.rfft(x * self.win[:, None], axis=0)) ** 2
        # Parseval, one-sided, undoing the window power: RMS without rumble below 100 Hz
        ms = 2 * spec[self.keep].sum(axis=0) / (BLOCK * (self.win ** 2).sum())
        self.peak_db, self.rms_db = db(peaks.max()), db(np.sqrt(ms.max()))
        self.n += 1
        if clipped:
            self.last_clip = self.n
        self.hist.append((self.rms_db, self.peak_db, clipped))

    def state(self):
        self.speech_db = None
        recent = list(self.hist)[-60:]       # 3 s
        if not recent:
            return "wait"
        if self.n - self.last_clip < 40:     # held 2 s
            return "clip"
        if len(recent) >= 20 and max(p for _, p, _ in recent) < -80:
            return "dead"
        floor = np.percentile([r for r, _, _ in self.hist], 10)
        gate = min(max(-55.0, floor + 8), -30.0)
        if sum(r > gate for r, _, _ in recent[-30:]) < 4:
            return "wait"
        active = [r for r, _, _ in recent if r > gate]
        self.speech_db = float(np.percentile(active, 80))
        if max(p for _, p, _ in recent) > HOT_PEAK or self.speech_db > HIGH:
            return "hot"
        return "low" if self.speech_db < LOW else "good"


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
        vols = [v["value_percent"] for v in s.get("volume", {}).values()]
        out[s["name"]] = dict(label=s.get("description") or s["name"], mute=s.get("mute", False),
                              gain=vols[0] if vols else "?",
                              ch=max(1, len(s.get("channel_map", "mono").split(","))))
    return out


def main():
    from PyQt6.QtCore import QProcess, QRectF, Qt, QTimer
    from PyQt6.QtGui import QColor, QFont, QIcon, QPainter
    from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QVBoxLayout, QWidget

    class Meter(QWidget):
        LO = -60.0
        def __init__(self):
            super().__init__()
            self.level = self.peak = self.hold = -120.0
            self.setMinimumHeight(64)

        def paintEvent(self, _):
            p = QPainter(self)
            w, h = self.width(), self.height() - 18
            x = lambda v: w * min(1, max(0, (v - self.LO) / -self.LO))
            for a, b, c in ((self.LO, LOW, "#1565c0"), (LOW, HIGH, "#2e7d32"),
                            (HIGH, HOT_PEAK, "#ef6c00"), (HOT_PEAK, 0, "#c62828")):
                col = QColor(c)
                p.fillRect(QRectF(x(a), 0, x(b) - x(a), h), col.darker(260))
                if self.level > a:
                    p.fillRect(QRectF(x(a), 0, x(min(b, self.level)) - x(a), h), col.lighter(130))
            p.fillRect(QRectF(x(self.hold) - 2, 0, 4, h), QColor("white"))
            p.setPen(QColor("white"))
            for v in (-50, -40, -26, -14, -6):
                p.drawText(QRectF(x(v) - 25, h, 50, 18), Qt.AlignmentFlag.AlignCenter, str(v))

    class Window(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Mic Level Light")
            self.resize(560, 380)
            self.pick = QComboBox()
            self.word, self.hint, self.info = QLabel(), QLabel(), QLabel()
            for lab, size, bold in ((self.word, 56, True), (self.hint, 16, False), (self.info, 11, False)):
                f = QFont(); f.setPointSize(size); f.setBold(bold)
                lab.setFont(f); lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.meter = Meter()
            box = QVBoxLayout(self)
            box.addWidget(self.pick); box.addWidget(self.word, 1)
            for w in (self.hint, self.meter, self.info):
                box.addWidget(w)
            self.proc, self.buf, self.cur, self.ch = None, b"", None, 1
            self.src, self.shown = {}, None
            self.an = Analyser()
            self.pick.currentIndexChanged.connect(self.poll)
            self.poll()
            for ms, fn in ((2000, self.poll), (60, self.draw)):
                t = QTimer(self); t.timeout.connect(fn); t.start(ms)

        def poll(self):
            self.src = sources()
            chosen = self.pick.currentData() or ""
            want = [("", "System default microphone")] + [(n, s["label"]) for n, s in self.src.items()]
            have = [(self.pick.itemData(i), self.pick.itemText(i)) for i in range(self.pick.count())]
            if want != have:
                self.pick.blockSignals(True)
                self.pick.clear()
                for n, label in want:
                    self.pick.addItem(label, n)
                self.pick.setCurrentIndex(max(0, self.pick.findData(chosen)))
                self.pick.blockSignals(False)
                chosen = self.pick.currentData()
            name = chosen or run("pactl", "get-default-source")
            alive = self.proc and self.proc.state() != QProcess.ProcessState.NotRunning
            if name != self.cur or not alive:
                self.open(name)

        def stop(self):
            if self.proc:
                self.proc.readyReadStandardOutput.disconnect()
                self.proc.kill(); self.proc.waitForFinished(500)
                self.proc.deleteLater()
                self.proc = None

        def open(self, name):
            self.stop()
            self.cur, self.buf, self.an = name, b"", Analyser()
            self.meter.hold = -120.0
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
                self.meter.hold = max(self.an.peak_db, self.meter.hold - 0.6)

        def draw(self):
            s = self.src.get(self.cur)
            st = "dead" if s is None or s["mute"] else self.an.state()
            word, hint, col = STATES[st]
            if st != self.shown:
                self.shown = st
                self.word.setText(word); self.hint.setText(hint)
                self.setStyleSheet(f"Window, QWidget {{ background: {col}; color: white; }}")
            m = self.meter
            m.level = max(self.an.rms_db, m.level - 2)
            m.update()
            sp = "–" if self.an.speech_db is None else f"{self.an.speech_db:.0f}"
            self.info.setText(f"speech {sp} dBFS (aim for -26 to -14)    peak {m.hold:.0f} dBFS    "
                              f"system gain {s['gain'] if s else '–'}" + ("    MUTED" if s and s["mute"] else ""))

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
