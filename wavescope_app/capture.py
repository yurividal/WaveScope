"""Packet-capture UI and helpers.

Contains monitor/managed capture dialogs, interface helpers,
and process orchestration for packet capture flows.
"""

from .core import *


def _detect_wifi_interfaces() -> List[Dict[str, str]]:
    """
    Parse `iw dev` output and return a list of dicts:
      { name, phy, type, connected_ssid }
    connected_ssid is "" when the interface is not associated.
    """
    try:
        out = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=4
        ).stdout
    except Exception:
        return []

    interfaces: List[Dict[str, str]] = []
    current_phy = ""
    current_if: Dict[str, str] = {}

    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("phy#"):
            current_phy = line
        elif line.startswith("Interface "):
            current_if = {
                "name": line.split()[1],
                "phy": current_phy,
                "type": "",
                "connected_ssid": "",
            }
            interfaces.append(current_if)
        elif line.startswith("type ") and current_if:
            current_if["type"] = line.split(None, 1)[1]
        elif line.startswith("ssid ") and current_if:
            current_if["connected_ssid"] = line.split(None, 1)[1]

    # Only managed (station) interfaces — skip existing monitor interfaces
    return [i for i in interfaces if i["type"] in ("managed", "AP", "")]


def _iw_chan_arg(channel: int, band: str) -> List[str]:
    """
    Return the `iw set channel` argument list for the given channel.
    For 6 GHz we pass the frequency directly; for 2.4/5 GHz the channel number.
    """
    if band == "6 GHz":
        freq = CH6.get(channel, 0)
        if freq:
            return [str(freq)]
    return [str(channel)]


_MONITOR_MASTER_TMPL = """\
#!/bin/bash
IFACE={iface}
MON=mon0
OUTPUT={output}
PID_FILE={pid_file}

# ── SETUP ──────────────────────────────────────────────
{nm_stop}ip link set "$IFACE" down
iw dev "$IFACE" interface add "$MON" type monitor 2>/dev/null || true
ip link set "$MON" up
iw dev "$MON" set channel {chan_args}
echo "WAVESCOPE_SETUP_OK"

# ── CAPTURE ─────────────────────────────────────────
tcpdump -i "$MON" -e -nn -U -w "$OUTPUT" &
TDPID=$!
echo "$TDPID" > "$PID_FILE"
wait "$TDPID"
rm -f "$PID_FILE" 2>/dev/null
echo "WAVESCOPE_CAPTURE_DONE"

# ── TEARDOWN ────────────────────────────────────────
ip link set "$MON" down 2>/dev/null || true
iw dev "$MON" del 2>/dev/null || true
ip link set "$IFACE" up 2>/dev/null || true
{nm_start}echo "WAVESCOPE_TEARDOWN_OK"
"""

_MONITOR_CLEANUP_TMPL = """\
#!/bin/bash
# Emergency cleanup — kills tcpdump by saved PID, tears down mon0, restores wifi
IFACE={iface}
MON=mon0
PID_FILE={pid_file}

if [[ -f "$PID_FILE" ]]; then
    TDPID=$(cat "$PID_FILE")
    kill -INT "$TDPID" 2>/dev/null || true
    sleep 1
    kill -KILL "$TDPID" 2>/dev/null || true
    rm -f "$PID_FILE"
fi
ip link set "$MON" down 2>/dev/null || true
iw dev "$MON" del 2>/dev/null || true
ip link set "$IFACE" up 2>/dev/null || true
{nm_start}echo "WAVESCOPE_CLEANUP_OK"
"""

_MANAGED_CAPTURE_TMPL = """\
#!/bin/bash
# Managed-mode capture — WiFi stays connected; only your machine's traffic.
IFACE={iface}
OUTPUT={output}
PID_FILE={pid_file}

tcpdump -i "$IFACE" -e -nn -U -w "$OUTPUT" &
TDPID=$!
echo "$TDPID" > "$PID_FILE"
echo "WAVESCOPE_CAPTURE_OK"
wait "$TDPID"
rm -f "$PID_FILE" 2>/dev/null
echo "WAVESCOPE_CAPTURE_DONE"
"""

_MANAGED_CLEANUP_TMPL = """\
#!/bin/bash
# Clean stop — sends SIGINT to tcpdump so it flushes the pcap properly.
PID_FILE={pid_file}

if [[ -f "$PID_FILE" ]]; then
    TDPID=$(cat "$PID_FILE")
    kill -INT "$TDPID" 2>/dev/null || true
    sleep 1
    kill -KILL "$TDPID" 2>/dev/null || true
    rm -f "$PID_FILE"
fi
echo "WAVESCOPE_CLEANUP_OK"
"""


class CaptureTypeDialog(QDialog):
    """Small picker — user chooses between Monitor Mode and Managed Mode capture."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f4e1  Packet Capture")
        self.setModal(True)
        self.setMinimumWidth(580)
        self._choice = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 18, 20, 18)

        title = QLabel("Choose capture type")
        title.setStyleSheet(
            f"font-size:13pt; font-weight:bold; color:{CAPTURE_TITLE_FG};"
        )
        layout.addWidget(title)

        note = QLabel("Both modes require a root password prompt (pkexec / Polkit).")
        note.setStyleSheet(f"font-size:9pt; color:{FALLBACK_GRAY};")
        layout.addWidget(note)
        layout.addSpacing(4)

        btn_mon = self._make_card(
            "\U0001f4e1  Monitor Mode",
            "True 802.11 over-the-air capture — all devices, all frames",
            "Disconnects your WiFi and creates a raw monitor interface (mon0).\n"
            "Captures ALL frames on the chosen channel — beacons, probes, data\n"
            "from every nearby device. Best for deep wireless analysis.",
            CAPTURE_CARD_MON_BG,
            CAPTURE_CARD_MON_HOVER,
        )
        btn_mon.clicked.connect(lambda: self._pick("monitor"))
        layout.addWidget(btn_mon)

        btn_mgd = self._make_card(
            "\U0001f310  Managed Mode",
            "Capture your own machine's traffic — WiFi stays connected",
            "Keeps your WiFi connection intact. Captures only traffic\n"
            "to/from this machine on the current network.\n"
            "Ideal for debugging your own connection without losing internet.",
            CAPTURE_CARD_MGD_BG,
            CAPTURE_CARD_MGD_HOVER,
        )
        btn_mgd.clicked.connect(lambda: self._pick("managed"))
        layout.addWidget(btn_mgd)

        layout.addSpacing(4)
        cancel = QPushButton("Cancel")
        cancel.setFixedWidth(90)
        cancel.clicked.connect(self.reject)
        hbox = QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(cancel)
        layout.addLayout(hbox)

    def _make_card(self, title, subtitle, body, bg, hover):
        # Use a QFrame subclass — embedding QLabels inside QPushButton
        # makes click detection unreliable in Qt6.
        class _Card(QFrame):
            clicked = pyqtSignal()

            def __init__(self, bg, hover):
                super().__init__()
                self._bg = bg
                self._hover = hover
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.setMinimumHeight(110)
                self._apply_style(bg)

            def _apply_style(self, color):
                self.setStyleSheet(
                    f"QFrame {{ background:{color}; border:1px solid {CAPTURE_CARD_BORDER};"
                    f" border-radius:8px; }}"
                )

            def enterEvent(self, _e):
                self._apply_style(self._hover)

            def leaveEvent(self, _e):
                self._apply_style(self._bg)

            def mousePressEvent(self, e):
                if e.button() == Qt.MouseButton.LeftButton:
                    self.clicked.emit()

        card = _Card(bg, hover)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(3)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(
            f"font-size:12pt; font-weight:bold; color:{CAPTURE_CARD_TITLE_FG};"
        )
        lbl_s = QLabel(subtitle)
        lbl_s.setStyleSheet(
            f"font-size:9.5pt; color:{CAPTURE_CARD_SUB_FG}; font-style:italic;"
        )
        lbl_b = QLabel(body)
        lbl_b.setStyleSheet(
            f"font-size:9pt; color:{CAPTURE_CARD_BODY_FG}; margin-top:4px;"
        )
        lbl_b.setWordWrap(True)
        for lbl in (lbl_t, lbl_s, lbl_b):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.addWidget(lbl_t)
        inner.addWidget(lbl_s)
        inner.addWidget(lbl_b)
        return card

    def _pick(self, choice: str):
        self._choice = choice
        self.accept()

    def chosen(self):
        return self._choice


class MonitorModeWindow(QDialog):
    """
    Packet-capture window using a temporary monitor-mode interface (mon0).
    Requires root via pkexec / Polkit.
    """

    # Internal capture states
    _ST_IDLE = "idle"
    _ST_SETUP = "setup"
    _ST_CAPTURE = "capture"
    _ST_TEARDOWN = "teardown"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📡  Monitor Mode  —  Packet Capture")
        self.setMinimumSize(620, 640)
        self.setModal(False)

        self._state = self._ST_IDLE
        self._proc = None
        self._cleanup_proc = None  # second pkexec for stop/teardown
        self._master_script = ""  # path to single temp script
        self._pid_file = ""  # tcpdump PID written here by master script
        self._stdout_buf = ""  # partial-line buffer for stdout
        self._start_time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._nm_was_running = False

        self._build_ui()
        self._populate_interfaces()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        # ── Warning banner ────────────────────────────────────────────────
        warn = QLabel(
            "⚠  Monitor mode requires <b>root privileges</b>.<br>"
            "The selected interface will be <b>temporarily disconnected</b> from WiFi "
            "while capture is running."
        )
        warn.setWordWrap(True)
        warn.setTextFormat(Qt.TextFormat.RichText)
        warn.setStyleSheet(
            f"QLabel {{ background:{CAPTURE_WARN_BG}; color:{CAPTURE_WARN_FG}; border:1px solid {CAPTURE_WARN_BORDER};"
            " border-radius:5px; padding:8px 12px; }"
        )
        layout.addWidget(warn)

        # ── Interface / channel configuration ────────────────────────────
        cfg = QFrame()
        cfg.setFrameShape(QFrame.Shape.StyledPanel)
        cfg_layout = QFormLayout(cfg)
        cfg_layout.setVerticalSpacing(8)
        cfg_layout.setHorizontalSpacing(14)
        cfg_layout.setContentsMargins(12, 10, 12, 10)

        self._iface_combo = QComboBox()
        self._iface_combo.setMinimumWidth(220)
        self._iface_combo.currentIndexChanged.connect(self._on_iface_change)
        cfg_layout.addRow("Interface:", self._iface_combo)

        self._band_sel = QComboBox()
        self._band_sel.addItems(["2.4 GHz", "5 GHz", "6 GHz"])
        self._band_sel.currentTextChanged.connect(self._on_band_sel)
        cfg_layout.addRow("Band:", self._band_sel)

        self._chan_combo = QComboBox()
        self._chan_combo.setMinimumWidth(180)
        cfg_layout.addRow("Channel:", self._chan_combo)

        # Output file row
        out_row = QWidget()
        out_hl = QHBoxLayout(out_row)
        out_hl.setContentsMargins(0, 0, 0, 0)
        out_hl.setSpacing(6)
        self._out_edit = QLineEdit()
        default_out = str(Path.home() / "capture.pcap")
        self._out_edit.setText(default_out)
        self._out_edit.setPlaceholderText("/path/to/output.pcap")
        out_hl.addWidget(self._out_edit)
        btn_browse = QPushButton("Browse…")
        btn_browse.setMaximumWidth(80)
        btn_browse.clicked.connect(self._on_browse)
        out_hl.addWidget(btn_browse)
        cfg_layout.addRow("Output file:", out_row)

        layout.addWidget(cfg)

        # ── Start / Stop button ───────────────────────────────────────────
        self._btn_start = QPushButton("▶  Start Capture")
        self._btn_start.setMinimumHeight(38)
        self._btn_start.setStyleSheet(
            f"QPushButton {{ background:{CAPTURE_BTN_START_BG}; color:{CAPTURE_BTN_START_FG}; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            f"QPushButton:hover {{ background:{CAPTURE_BTN_START_HOVER}; }}"
            f"QPushButton:disabled {{ background:{CAPTURE_BTN_DIS_BG}; color:{CAPTURE_BTN_DIS_FG}; }}"
        )
        self._btn_start.clicked.connect(self._on_start_stop)
        layout.addWidget(self._btn_start)

        # ── Status row ────────────────────────────────────────────────────
        stats_row = QHBoxLayout()
        self._lbl_state = QLabel("Idle")
        self._lbl_state.setStyleSheet(f"font-weight:bold; color:{BTN_ACCENT};")
        self._lbl_elapsed = QLabel("00:00")
        self._lbl_elapsed.setStyleSheet(
            f"color:{GRAPH_FG_DARK}; font-family:monospace;"
        )
        self._lbl_size = QLabel("")
        self._lbl_size.setStyleSheet(f"color:{GRAPH_FG_DARK};")
        stats_row.addWidget(self._lbl_state)
        stats_row.addStretch()
        stats_row.addWidget(QLabel("Elapsed: "))
        stats_row.addWidget(self._lbl_elapsed)
        stats_row.addWidget(QLabel("   File: "))
        stats_row.addWidget(self._lbl_size)
        layout.addLayout(stats_row)

        # ── Log area ──────────────────────────────────────────────────────
        from PyQt6.QtWidgets import QPlainTextEdit

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setStyleSheet(
            f"QPlainTextEdit {{ background:{CAPTURE_LOG_BG}; color:{CAPTURE_LOG_FG};"
            " font-family:monospace; font-size:9pt; border-radius:4px; }"
        )
        layout.addWidget(self._log)

        # Populate band → channel on start
        self._on_band_sel(self._band_sel.currentText())

    # ── Populate helpers ──────────────────────────────────────────────────

    def _populate_interfaces(self):
        self._ifaces = _detect_wifi_interfaces()
        self._iface_combo.clear()
        if not self._ifaces:
            self._iface_combo.addItem("No WiFi interfaces found")
            self._btn_start.setEnabled(False)
            return
        for ifc in self._ifaces:
            label = ifc["name"]
            if ifc["connected_ssid"]:
                label += f"  (connected: {ifc['connected_ssid']})"
            self._iface_combo.addItem(label, ifc["name"])

    def _on_iface_change(self, _idx):
        pass  # could refresh band capabilities in future

    def _on_band_sel(self, band: str):
        self._chan_combo.clear()
        if band == "2.4 GHz":
            src = CH24
        elif band == "5 GHz":
            src = CH5
        else:
            src = CH6
        for ch, freq in sorted(src.items(), key=lambda x: x[1]):
            self._chan_combo.addItem(f"Ch {ch}  ({freq} MHz)", ch)

    def _on_browse(self):
        from PyQt6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose output file",
            str(Path.home()),
            "PCAP files (*.pcap);;All files (*)",
        )
        if path:
            if not path.endswith(".pcap"):
                path += ".pcap"
            self._out_edit.setText(path)

    # ── Capture control ───────────────────────────────────────────────────

    def _on_start_stop(self):
        if self._state == self._ST_IDLE:
            self._start_capture()
        else:
            self._request_stop()

    def _start_capture(self):
        iface = self._iface_combo.currentData()
        if not iface:
            self._log_line("⚠  No interface selected.")
            return
        channel = self._chan_combo.currentData()
        if not channel:
            self._log_line("⚠  No channel selected.")
            return
        output = self._out_edit.text().strip()
        if not output:
            self._log_line("⚠  No output file specified.")
            return

        band = self._band_sel.currentText()
        self._iface_name = iface
        self._output_path = output
        self._channel = channel
        self._band = band

        # Check & record if NetworkManager is running so we restore it
        nm_check = subprocess.run(
            ["systemctl", "is-active", "NetworkManager"], capture_output=True, text=True
        )
        self._nm_was_running = nm_check.returncode == 0

        self._log_line(f"Interface : {iface}")
        self._log_line(f"Band/Chan : {band}  ch {channel}")
        self._log_line(f"Output    : {output}")
        self._log_line(f"NM active : {self._nm_was_running}")
        self._log_line("─" * 50)

        self._run_master()

    def _run_master(self):
        """Build and launch the single combined pkexec script."""
        self._set_state(self._ST_SETUP, "Setting up monitor interface…")

        chan_args = " ".join(_iw_chan_arg(self._channel, self._band))
        nm_stop = "systemctl stop NetworkManager\n" if self._nm_was_running else ""
        nm_start = "systemctl start NetworkManager\n" if self._nm_was_running else ""

        import tempfile as _tf

        self._pid_file = _tf.mktemp(prefix="wavescope_tdpid_", suffix=".pid")
        script_body = _MONITOR_MASTER_TMPL.format(
            iface=self._iface_name,
            output=self._output_path,
            chan_args=chan_args,
            nm_stop=nm_stop,
            nm_start=nm_start,
            pid_file=self._pid_file,
        )
        self._master_script = self._write_temp_script(script_body)
        self._stdout_buf = ""

        self._proc = self._make_process()
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.start("pkexec", ["bash", self._master_script])
        self._log_line("▶  Starting (Polkit authentication may appear…)")

    def _on_stdout(self):
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if line == "WAVESCOPE_SETUP_OK":
                self._log_line("✓  Monitor interface mon0 ready.")
                self._set_state(self._ST_CAPTURE, "Capturing…")
                self._start_time = time.monotonic()
                self._timer.start()
                self._log_line("▶  tcpdump running — click Stop to end capture.")
            elif line == "WAVESCOPE_CAPTURE_DONE":
                self._timer.stop()
                self._set_state(self._ST_TEARDOWN, "Restoring interface…")
                self._log_line("▶  Restoring interface and NetworkManager…")
            elif line == "WAVESCOPE_TEARDOWN_OK":
                self._log_line("✓  Interface and NetworkManager restored.")
            else:
                self._log_line(f"  {line}")

    def _on_stderr(self):
        data = bytes(self._proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_proc_finished(self, exit_code: int, _exit_status):
        self._timer.stop()
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        for line in self._stdout_buf.splitlines():
            ln = line.strip()
            if ln and not ln.startswith("WAVESCOPE_"):
                self._log_line(f"  {ln}")
        self._stdout_buf = ""

        if exit_code != 0 and self._state == self._ST_SETUP:
            self._log_line(
                f"✗  Setup/auth failed (exit {exit_code}). "
                "Check pkexec and iw are installed."
            )

        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(f"📁  Saved {sz / 1024:.1f} KB → {self._output_path}")
        except OSError:
            pass

        # Only reset UI if cleanup hasn't already done it
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle — capture complete")
        try:
            if self._master_script:
                os.unlink(self._master_script)
                self._master_script = ""
        except OSError:
            pass
        try:
            if self._pid_file and os.path.exists(self._pid_file):
                os.unlink(self._pid_file)
                self._pid_file = ""
        except OSError:
            pass

    def _reset_ui_to_idle(self, label: str = "Idle"):
        self._set_state(self._ST_IDLE, label)
        self._btn_start.setText("▶  Start Capture")
        self._btn_start.setStyleSheet(
            f"QPushButton {{ background:{CAPTURE_BTN_START_BG}; color:{CAPTURE_BTN_START_FG}; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            f"QPushButton:hover {{ background:{CAPTURE_BTN_START_HOVER}; }}"
            f"QPushButton:disabled {{ background:{CAPTURE_BTN_DIS_BG}; color:{CAPTURE_BTN_DIS_FG}; }}"
        )
        self._btn_start.setEnabled(True)
        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(f"📁  Saved {sz / 1024:.1f} KB → {self._output_path}")
        except OSError:
            pass

    def _request_stop(self):
        if self._state in (self._ST_CAPTURE, self._ST_SETUP) and self._proc:
            self._btn_start.setEnabled(False)
            self._btn_start.setText("⏳  Stopping…")
            self._log_line(
                "⏹  Stopping — launching cleanup (a password prompt may appear)…"
            )
            self._set_state(self._ST_TEARDOWN, "Stopping…")
            self._run_cleanup()
            # Last-resort force-kill if cleanup pkexec itself hangs
            QTimer.singleShot(20000, self._force_kill_capture)

    def _run_cleanup(self):
        nm_start = "systemctl start NetworkManager\n" if self._nm_was_running else ""
        script_body = _MONITOR_CLEANUP_TMPL.format(
            iface=self._iface_name,
            pid_file=self._pid_file,
            nm_start=nm_start,
        )
        cleanup_path = self._write_temp_script(script_body)
        self._cleanup_proc = self._make_process()
        self._cleanup_proc.readyReadStandardOutput.connect(self._on_cleanup_stdout)
        self._cleanup_proc.readyReadStandardError.connect(self._on_cleanup_stderr)
        self._cleanup_proc.finished.connect(
            lambda code, _s, p=cleanup_path: self._on_cleanup_finished(code, p)
        )
        self._cleanup_proc.start("pkexec", ["bash", cleanup_path])
        self._log_line("▶  Cleanup running…")

    def _on_cleanup_stdout(self):
        data = bytes(self._cleanup_proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        for line in data.splitlines():
            ln = line.strip()
            if ln == "WAVESCOPE_CLEANUP_OK":
                self._log_line("✓  Interface and NetworkManager restored.")
            elif ln:
                self._log_line(f"  {ln}")

    def _on_cleanup_stderr(self):
        data = bytes(self._cleanup_proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_cleanup_finished(self, exit_code: int, cleanup_path: str):
        try:
            os.unlink(cleanup_path)
        except OSError:
            pass
        self._cleanup_proc = None
        if exit_code != 0:
            self._log_line(f"⚠  Cleanup exited with code {exit_code}.")
        # Reset UI — master process may still be exiting but that's fine
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle — capture stopped")

    def _force_kill_capture(self):
        from PyQt6.QtCore import QProcess

        if (
            self._state != self._ST_IDLE
            and self._proc
            and self._proc.state() != QProcess.ProcessState.NotRunning
        ):
            self._log_line(
                "⚠  Still running after 20 s — force-killing master process…"
            )
            self._proc.kill()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _make_process(self) -> "QProcess":
        from PyQt6.QtCore import QProcess

        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        return p

    def _write_temp_script(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh", prefix="wavescope_")
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        return path

    def _set_state(self, state: str, label: str):
        self._state = state
        self._lbl_state.setText(label)
        idle = state == self._ST_IDLE
        self._iface_combo.setEnabled(idle)
        self._band_sel.setEnabled(idle)
        self._chan_combo.setEnabled(idle)
        self._out_edit.setEnabled(idle)
        if state == self._ST_CAPTURE:
            self._btn_start.setText("⏹  Stop Capture")
            self._btn_start.setStyleSheet(
                f"QPushButton {{ background:{CAPTURE_BTN_STOP_BG}; color:{CAPTURE_BTN_STOP_FG}; border:none;"
                " border-radius:5px; font-size:11pt; font-weight:bold; }"
                f"QPushButton:hover {{ background:{CAPTURE_BTN_STOP_HOVER}; }}"
            )
            self._btn_start.setEnabled(True)
        elif state in (self._ST_SETUP, self._ST_TEARDOWN):
            self._btn_start.setText("⏹  Stop Capture")
            self._btn_start.setEnabled(state == self._ST_SETUP)
        elif idle:
            self._btn_start.setEnabled(True)

    def _tick(self):
        elapsed = int(time.monotonic() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._lbl_elapsed.setText(f"{m:02d}:{s:02d}")
        try:
            sz = os.path.getsize(self._output_path)
            if sz < 1024 * 1024:
                self._lbl_size.setText(f"{sz / 1024:.1f} KB")
            else:
                self._lbl_size.setText(f"{sz / 1024 / 1024:.2f} MB")
        except OSError:
            self._lbl_size.setText("—")

    def _log_line(self, text: str):
        self._log.appendPlainText(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        if self._state != self._ST_IDLE:
            from PyQt6.QtWidgets import QMessageBox

            r = QMessageBox.question(
                self,
                "Capture in progress",
                "A capture is running. Stop it and restore the interface before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r == QMessageBox.StandardButton.Yes:
                self._request_stop()
                event.ignore()  # re-close after teardown finishes
                # Reconnect to close after teardown
                return
            else:
                event.ignore()
                return
        event.accept()


class ManagedCaptureWindow(QDialog):
    """
    Managed-mode packet capture — WiFi stays connected.
    Only captures traffic to/from this machine. Requires root via pkexec.
    """

    _ST_IDLE = "idle"
    _ST_CAPTURE = "capture"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f310  Managed Capture  \u2014  Packet Capture")
        self.setMinimumSize(560, 540)
        self.setModal(False)

        self._state = self._ST_IDLE
        self._proc = None
        self._cleanup_proc = None
        self._capture_script = ""
        self._pid_file = ""
        self._stdout_buf = ""
        self._start_time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._iface_name = ""
        self._output_path = ""

        self._build_ui()
        self._populate_interfaces()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        banner = QLabel(
            "\u2139  Your WiFi connection stays active. Only traffic to/from "
            "this machine is captured."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            f"background:{CAPTURE_BANNER_BG}; color:{CAPTURE_BANNER_FG}; padding:8px 10px;"
            " border-radius:5px; font-size:9pt;"
        )
        layout.addWidget(banner)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._iface_combo = QComboBox()
        form.addRow("Interface:", self._iface_combo)

        out_row = QHBoxLayout()
        self._out_edit = QLineEdit(
            os.path.expanduser(f"~/Desktop/managed_{int(time.time())}.pcap")
        )
        btn_browse = QPushButton("Browse\u2026")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(btn_browse)
        form.addRow("Output file:", out_row)
        layout.addLayout(form)

        status_row = QHBoxLayout()
        self._lbl_state = QLabel("Idle")
        self._lbl_elapsed = QLabel("00:00")
        self._lbl_size = QLabel("File:  0 KB")
        self._lbl_state.setStyleSheet(
            f"color:{CAPTURE_MGD_STATE_FG}; font-weight:bold;"
        )
        status_row.addWidget(self._lbl_state)
        status_row.addStretch()
        status_row.addWidget(QLabel("Elapsed:"))
        status_row.addWidget(self._lbl_elapsed)
        status_row.addSpacing(12)
        status_row.addWidget(self._lbl_size)
        layout.addLayout(status_row)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"background:{CAPTURE_MGD_LOG_BG}; color:{CAPTURE_MGD_LOG_FG}; font-family:monospace;"
            " font-size:9pt; border-radius:4px;"
        )
        layout.addWidget(self._log, 1)

        self._btn_start = QPushButton("\u25b6  Start Capture")
        self._btn_start.setMinimumHeight(42)
        self._btn_start.setStyleSheet(
            f"QPushButton {{ background:{CAPTURE_BTN_START_BG}; color:{CAPTURE_BTN_START_FG}; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            f"QPushButton:hover {{ background:{CAPTURE_BTN_START_HOVER}; }}"
            f"QPushButton:disabled {{ background:{CAPTURE_BTN_DIS_BG}; color:{CAPTURE_BTN_DIS_FG}; }}"
        )
        self._btn_start.clicked.connect(self._on_btn)
        layout.addWidget(self._btn_start)

    def _populate_interfaces(self):
        ifaces = _detect_wifi_interfaces()
        self._iface_combo.clear()
        if not ifaces:
            self._iface_combo.addItem("No WiFi interfaces found")
            self._btn_start.setEnabled(False)
            return
        for ifc in ifaces:
            label = ifc["name"]
            if ifc["connected_ssid"]:
                label += f"  (connected: {ifc['connected_ssid']})"
            self._iface_combo.addItem(label, ifc["name"])

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Capture File",
            os.path.expanduser("~/Desktop"),
            "PCAP files (*.pcap);;All files (*)",
        )
        if path:
            self._out_edit.setText(path)

    # ── Capture lifecycle ─────────────────────────────────────────────────

    def _on_btn(self):
        if self._state == self._ST_IDLE:
            self._start_capture()
        else:
            self._request_stop()

    def _start_capture(self):
        iface = (
            self._iface_combo.currentData() or self._iface_combo.currentText()
        ).strip()
        output = self._out_edit.text().strip()
        if not iface:
            QMessageBox.warning(self, "No Interface", "Select a WiFi interface.")
            return
        if not output:
            QMessageBox.warning(self, "No Output", "Choose an output file.")
            return
        self._iface_name = iface
        self._output_path = output
        self._log.clear()
        self._log_line(f"Interface : {iface}")
        self._log_line(f"Output    : {output}")
        self._log_line("\u2500" * 50)
        self._run_capture()

    def _run_capture(self):
        import tempfile as _tf

        self._pid_file = _tf.mktemp(prefix="wavescope_tdpid_", suffix=".pid")
        script_body = _MANAGED_CAPTURE_TMPL.format(
            iface=self._iface_name,
            output=self._output_path,
            pid_file=self._pid_file,
        )
        self._capture_script = self._write_temp_script(script_body)
        self._stdout_buf = ""
        self._proc = self._make_process()
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.start("pkexec", ["bash", self._capture_script])
        self._set_state(self._ST_CAPTURE, "Starting\u2026")
        self._btn_start.setText("\u23f9  Stop Capture")
        self._btn_start.setStyleSheet(
            f"QPushButton {{ background:{CAPTURE_BTN_STOP_BG}; color:{CAPTURE_BTN_STOP_FG}; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            f"QPushButton:hover {{ background:{CAPTURE_BTN_STOP_HOVER}; }}"
        )
        self._log_line("\u25b6  Starting (Polkit authentication may appear\u2026)")

    def _on_stdout(self):
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if line == "WAVESCOPE_CAPTURE_OK":
                self._log_line(
                    "\u2713  tcpdump running \u2014 WiFi connection is intact."
                )
                self._set_state(self._ST_CAPTURE, "Capturing\u2026")
                self._start_time = time.monotonic()
                self._timer.start()
                self._log_line("\u25b6  Click Stop to end capture.")
            elif line == "WAVESCOPE_CAPTURE_DONE":
                self._log_line("\u2713  Capture complete.")
            else:
                self._log_line(f"  {line}")

    def _on_stderr(self):
        data = bytes(self._proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_proc_finished(self, exit_code: int, _exit_status):
        self._timer.stop()
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        for line in self._stdout_buf.splitlines():
            ln = line.strip()
            if ln and not ln.startswith("WAVESCOPE_"):
                self._log_line(f"  {ln}")
        self._stdout_buf = ""
        if exit_code != 0 and self._state == self._ST_CAPTURE:
            self._log_line(
                f"\u2717  Capture failed (exit {exit_code}). Check pkexec is available."
            )
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle \u2014 capture complete")
        self._cleanup_temps()

    def _request_stop(self):
        if self._state == self._ST_CAPTURE and self._proc:
            self._btn_start.setEnabled(False)
            self._btn_start.setText("\u23f3  Stopping\u2026")
            self._log_line(
                "\u23f9  Stopping \u2014 launching cleanup (a password prompt may appear)\u2026"
            )
            self._run_cleanup()
            QTimer.singleShot(20000, self._force_kill)

    def _run_cleanup(self):
        script_body = _MANAGED_CLEANUP_TMPL.format(pid_file=self._pid_file)
        cleanup_path = self._write_temp_script(script_body)
        self._cleanup_proc = self._make_process()
        self._cleanup_proc.readyReadStandardOutput.connect(self._on_cleanup_stdout)
        self._cleanup_proc.readyReadStandardError.connect(self._on_cleanup_stderr)
        self._cleanup_proc.finished.connect(
            lambda code, _s, p=cleanup_path: self._on_cleanup_finished(code, p)
        )
        self._cleanup_proc.start("pkexec", ["bash", cleanup_path])
        self._log_line("\u25b6  Cleanup running\u2026")

    def _on_cleanup_stdout(self):
        data = bytes(self._cleanup_proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        for line in data.splitlines():
            ln = line.strip()
            if ln == "WAVESCOPE_CLEANUP_OK":
                self._log_line("\u2713  Capture stopped cleanly.")
            elif ln:
                self._log_line(f"  {ln}")

    def _on_cleanup_stderr(self):
        data = bytes(self._cleanup_proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_cleanup_finished(self, exit_code: int, cleanup_path: str):
        try:
            os.unlink(cleanup_path)
        except OSError:
            pass
        self._cleanup_proc = None
        if exit_code != 0:
            self._log_line(f"\u26a0  Cleanup exited with code {exit_code}.")
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle \u2014 capture stopped")
        self._cleanup_temps()

    def _force_kill(self):
        from PyQt6.QtCore import QProcess

        if (
            self._state != self._ST_IDLE
            and self._proc
            and self._proc.state() != QProcess.ProcessState.NotRunning
        ):
            self._log_line(
                "\u26a0  Still running after 20 s \u2014 force-killing\u2026"
            )
            self._proc.kill()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _reset_ui_to_idle(self, label: str = "Idle"):
        self._set_state(self._ST_IDLE, label)
        self._btn_start.setText("\u25b6  Start Capture")
        self._btn_start.setStyleSheet(
            f"QPushButton {{ background:{CAPTURE_BTN_START_BG}; color:{CAPTURE_BTN_START_FG}; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            f"QPushButton:hover {{ background:{CAPTURE_BTN_START_HOVER}; }}"
            f"QPushButton:disabled {{ background:{CAPTURE_BTN_DIS_BG}; color:{CAPTURE_BTN_DIS_FG}; }}"
        )
        self._btn_start.setEnabled(True)
        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(
                f"\U0001f4c1  Saved {sz / 1024:.1f} KB \u2192 {self._output_path}"
            )
        except OSError:
            pass

    def _cleanup_temps(self):
        for attr in ("_capture_script", "_pid_file"):
            path = getattr(self, attr, "")
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                setattr(self, attr, "")

    def _set_state(self, state: str, label: str):
        self._state = state
        self._lbl_state.setText(label)
        idle = state == self._ST_IDLE
        self._iface_combo.setEnabled(idle)
        self._out_edit.setEnabled(idle)

    def _tick(self):
        elapsed = int(time.monotonic() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._lbl_elapsed.setText(f"{m:02d}:{s:02d}")
        try:
            sz = os.path.getsize(self._output_path)
            if sz < 1024 * 1024:
                self._lbl_size.setText(f"File:  {sz / 1024:.1f} KB")
            else:
                self._lbl_size.setText(f"File:  {sz / 1024 / 1024:.2f} MB")
        except OSError:
            pass

    def _log_line(self, text: str):
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _make_process(self):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        return p

    def _write_temp_script(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh", prefix="wavescope_")
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        return path

    def closeEvent(self, event):
        if self._state != self._ST_IDLE:
            self._request_stop()
            event.ignore()
        else:
            event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
