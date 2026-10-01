""""Find AP" — a signal meter with a Geiger-counter style beeper.

The tone repeats faster and higher as the signal gets stronger, so the AP
can be located by walking without looking at the screen.

Audio goes through the desktop's own player (`pw-play`, `paplay` or
`aplay`) rather than Qt Multimedia, whose codec/backend libraries the
AppImage and the distro packages cannot rely on.  Without any player the
meter still works and Qt's system beep is used.
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from typing import Dict, List, Optional

from .core import *  # noqa: F401,F403  (Qt widgets, AccessPoint, colours)

PLAYERS = ("pw-play", "paplay", "aplay")
DBM_MIN, DBM_MAX = -95.0, -30.0  # meter / tone mapping range
PITCHES_HZ = [440, 523, 622, 740, 880, 1047, 1245, 1480, 1760]  # musical steps


def find_player() -> Optional[str]:
    for name in PLAYERS:
        path = shutil.which(name)
        if path:
            return path
    return None


def _norm(dbm: float) -> float:
    return max(0.0, min(1.0, (dbm - DBM_MIN) / (DBM_MAX - DBM_MIN)))


def beep_interval_ms(dbm: float) -> int:
    """1.5 s between beeps at -95 dBm down to 0.12 s at -30 dBm."""
    return int(round(1500 - _norm(dbm) * (1500 - 120)))


def pitch_index(dbm: float) -> int:
    return min(len(PITCHES_HZ) - 1, int(_norm(dbm) * len(PITCHES_HZ)))


class ToneBeeper:
    """Pre-renders short sine beeps and plays them without blocking."""

    def __init__(self):
        self.player = find_player()
        self._dir = tempfile.mkdtemp(prefix="wavescope-tones-")
        self._files: Dict[int, str] = {}
        self._proc: Optional[subprocess.Popen] = None

    def _tone(self, idx: int) -> str:
        if idx not in self._files:
            path = os.path.join(self._dir, f"tone{idx}.wav")
            rate, dur, freq = 22050, 0.07, PITCHES_HZ[idx]
            n = int(rate * dur)
            fade = int(rate * 0.006)
            frames = bytearray()
            for i in range(n):
                env = min(1.0, i / fade, (n - i) / fade)  # click-free fade in/out
                frames += struct.pack("<h", int(12000 * env * math.sin(2 * math.pi * freq * i / rate)))
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(bytes(frames))
            self._files[idx] = path
        return self._files[idx]

    def beep(self, dbm: float) -> None:
        if self.player is None:
            QApplication.beep()
            return
        if self._proc is not None and self._proc.poll() is None:
            return  # previous beep still playing: skip rather than queue up
        try:
            self._proc = subprocess.Popen(
                [self.player, self._tone(pitch_index(dbm))],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.player = None

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)


class FindAPDialog(QDialog):
    """Non-modal meter for one BSSID, fed by MainWindow._on_data each scan."""

    def __init__(self, bssid: str, ssid: str, parent=None, sound: bool = True):
        super().__init__(parent)
        self._bssid = bssid.lower()
        self._beeper = ToneBeeper()
        self._dbm: Optional[float] = None
        self._history: List[float] = []
        self._last_update = 0.0
        self.setWindowTitle(f"Find AP — {ssid or bssid}")
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)
        self._lbl_target = QLabel(f"<b>{html.escape(ssid or '<hidden>')}</b><br><tt>{bssid}</tt>")
        self._lbl_target.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self._lbl_target)

        self._lbl_dbm = QLabel("— dBm")
        f = QFont()
        f.setPointSize(30)
        f.setBold(True)
        self._lbl_dbm.setFont(f)
        self._lbl_dbm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl_dbm)

        self._bar = QProgressBar()
        self._bar.setRange(int(DBM_MIN), int(DBM_MAX))
        self._bar.setTextVisible(False)
        lay.addWidget(self._bar)

        self._lbl_info = QLabel("Waiting for the next scan…")
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet(f"color:{HTML_MUTED}; font-size:9pt;")
        lay.addWidget(self._lbl_info)

        row = QHBoxLayout()
        self._chk_sound = QCheckBox("Sound")
        self._chk_sound.setChecked(sound)
        if self._beeper.player is None:
            self._chk_sound.setToolTip("No pw-play / paplay / aplay found — using the system beep")
        row.addWidget(self._chk_sound)
        row.addStretch()
        btn = QPushButton("Close")
        btn.clicked.connect(self.close)
        row.addWidget(btn)
        lay.addLayout(row)

        note = QLabel(
            "Signal updates with each scan. For the connected AP every refresh cycle; "
            "for other APs whenever the system scans (NetworkManager allows about one scan every 10 s)."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{HTML_MUTED}; font-size:8pt;")
        lay.addWidget(note)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    @property
    def bssid(self) -> str:
        return self._bssid

    def update_aps(self, aps: List[AccessPoint]) -> None:
        ap = next((a for a in aps if a.bssid.lower() == self._bssid), None)
        if ap is None or ap.is_lingering:
            self._lbl_info.setText("Not heard in the latest scan.")
            return
        # The connected AP's link signal is refreshed every cycle (iw link);
        # scan-cache RSSI only changes when a scan runs.
        live = ap.in_use and ap.conn_link_signal_dbm is not None
        dbm = float(ap.conn_link_signal_dbm) if live else float(ap.dbm)
        self._history = (self._history + [dbm])[-30:]
        self._dbm = dbm
        self._last_update = time.monotonic()
        self._lbl_dbm.setText(f"{dbm:.0f} dBm")
        self._lbl_dbm.setStyleSheet(f"color:{dbm_color(dbm).name()};")
        self._bar.setValue(int(max(DBM_MIN, min(DBM_MAX, dbm))))
        trend = ""
        if len(self._history) >= 3:
            delta = self._history[-1] - sum(self._history[-4:-1]) / len(self._history[-4:-1])
            trend = "  ▲ stronger" if delta >= 2 else "  ▼ weaker" if delta <= -2 else "  ● steady"
        src = "live link signal" if live else (
            f"scan, heard {ap.last_seen_ms / 1000:.0f} s ago" if ap.last_seen_ms is not None else "scan"
        )
        self._lbl_info.setText(
            f"{ap.band} ch {ap.channel} · min {min(self._history):.0f} / max {max(self._history):.0f} dBm"
            f" · {src}{trend}"
        )
        if not self._timer.isActive():
            self._tick()

    def _tick(self) -> None:
        if self._dbm is None:
            return
        if self._chk_sound.isChecked():
            self._beeper.beep(self._dbm)
        self._timer.start(beep_interval_ms(self._dbm))

    def closeEvent(self, event):
        self._timer.stop()
        self._beeper.close()
        super().closeEvent(event)
