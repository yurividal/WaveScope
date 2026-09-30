"""Packet-capture UI and helpers.

Contains monitor/managed capture dialogs, interface helpers,
and process orchestration for packet capture flows.

Privilege model
---------------
Every privileged action runs a *fixed* bash script as
``pkexec bash <script> <args...>``.  User-controlled values (interface,
output path, frequencies, PID-file path) are never interpolated into script
text: they reach bash only as quoted positional parameters, and are validated
in Python before launch.  Scripts and the tcpdump PID file live in a
per-capture private directory created by ``tempfile.mkdtemp`` (mode 0700).
"""

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from .core import *


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Linux IFNAMSIZ is 16 incl. NUL -> max 15 chars.  Restrict to a safe charset.
_IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")

_MON_IFACE = "mon0"  # must match MON= in _MONITOR_MASTER_SCRIPT

_BAND_CHANNELS: Dict[str, Dict[int, int]] = {
    "2.4 GHz": CH24,
    "5 GHz": CH5,
    "6 GHz": CH6,
}

_WIDTHS: Tuple[int, ...] = (20, 40, 80, 160)

# 5 GHz bonded-block first channels (IEEE 802.11 channelization).
# A block of width W starting at s spans s, s+4, ..., s+(W/20-1)*4.
_CH5_BLOCK_STARTS: Dict[int, Tuple[int, ...]] = {
    40: (36, 44, 52, 60, 100, 108, 116, 124, 132, 140, 149, 157, 165, 173),
    80: (36, 52, 100, 116, 132, 149),
    160: (36, 100, 149),  # 149-177 only valid if every channel is in CH5
}

# pkexec exit codes: 126 = auth dialog dismissed, 127 = not authorized
_PKEXEC_AUTH_EXIT = (126, 127)

# After cleanup succeeded, how long the master gets to run its EXIT trap
# before we fall back to force-killing it.
_FORCE_KILL_GRACE_MS = 15000


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (no Qt, unit-testable)
# ─────────────────────────────────────────────────────────────────────────────


def _detect_wifi_interfaces() -> List[Dict[str, str]]:
    """
    Parse `iw dev` output and return a list of dicts:
      { name, phy, type, connected_ssid }
    connected_ssid is "" when the interface is not associated.
    """
    try:
        out = subprocess.run(
            [IW_BIN, "dev"], capture_output=True, text=True, timeout=4
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


def _valid_iface(name: object) -> bool:
    """True if *name* is a plausible Linux interface name (safe charset)."""
    return isinstance(name, str) and bool(_IFACE_RE.match(name))


def _validate_output_path(raw: str) -> Tuple[Optional[str], str]:
    """
    Validate a user-supplied pcap output path.

    Returns (normalized_absolute_path, "") on success, or (None, error_text).
    `~` is expanded; the path must be absolute, contain no newline/NUL, not
    be a directory, and its parent directory must exist.  Spaces are fine:
    the path is passed to bash as a quoted positional argument.
    """
    if not raw:
        return None, "No output file specified."
    if any(c in raw for c in ("\n", "\r", "\0")):
        return None, "Output path must not contain newline or NUL characters."
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        return None, "Output path must be absolute (e.g. /home/you/capture.pcap)."
    path = os.path.normpath(path)
    # POSIX normpath preserves a leading '//' — collapse it
    if path.startswith("//"):
        path = "/" + path.lstrip("/")
    if os.path.isdir(path):
        return None, f"Output path is a directory: {path}"
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        return None, f"Output directory does not exist: {parent}"
    return path, ""


def _bonded_block(channel: int, band: str, width: int) -> Optional[Tuple[int, int]]:
    """
    Return (first_channel, last_channel) of the standard 5/6 GHz bonded
    block of *width* MHz that contains *channel*, or None if no valid block
    exists (e.g. channel 165 @ 80 MHz, 6 GHz ch 233 @ 40 MHz).
    """
    n_sub = width // 20  # number of 20 MHz subchannels in the block
    if n_sub < 2:
        return None
    if band == "5 GHz":
        table = CH5
        span = (n_sub - 1) * 4
        first = next(
            (s for s in _CH5_BLOCK_STARTS.get(width, ()) if s <= channel <= s + span),
            None,
        )
        if first is None:
            return None
    elif band == "6 GHz":
        table = CH6
        step = n_sub * 4  # 40 -> 8, 80 -> 16, 160 -> 32; blocks start at ch 1
        first = 1 + ((channel - 1) // step) * step
    else:
        return None
    block = [first + 4 * i for i in range(n_sub)]
    if channel not in block or any(c not in table for c in block):
        return None
    return first, block[-1]


def _effective_width(channel: int, band: str, width: int) -> int:
    """Width actually usable for *channel*; falls back to 20 when invalid."""
    if width not in _WIDTHS or width == 20:
        return 20
    if band == "2.4 GHz":
        # HT40 only; ch 14 (Japan, 802.11b only) has no 40 MHz mode
        return 40 if width == 40 and 1 <= channel <= 13 else 20
    return width if _bonded_block(channel, band, width) else 20


def _iw_freq_args(channel: int, band: str, width: int) -> list[str]:
    """
    Arguments for `iw dev <mon> set freq ...` (after the literal "freq").

    iw syntax (iw 6.x `iw help`):
      set freq <freq> [NOHT|HT20|HT40+|HT40-|...]
      set freq <control freq> [5|10|20|40|80|80+80|160|320] [<center1_freq>]

    - 20 MHz (or fallback): just the control frequency.
    - 2.4 GHz 40 MHz: HT40+ for ch <= 7, else HT40-.
    - 5/6 GHz 40/80/160: <control> <width> <center1>, center1 being the
      midpoint of the first and last 20 MHz channel of the standard block.

    Frequencies are used for every band because 6 GHz channel numbers
    overlap 2.4/5 GHz numbers and `set channel` would be ambiguous.
    Raises ValueError for an unknown band/channel.
    """
    table = _BAND_CHANNELS.get(band)
    if table is None or channel not in table:
        raise ValueError(f"unknown channel {channel!r} for band {band!r}")
    control = table[channel]
    eff = _effective_width(channel, band, width)
    if eff == 20:
        return [str(control)]
    if band == "2.4 GHz":
        return [str(control), "HT40+" if channel <= 7 else "HT40-"]
    block = _bonded_block(channel, band, eff)
    if block is None:  # unreachable: _effective_width already validated it
        return [str(control)]
    first, last = block
    center1 = (table[first] + table[last]) // 2
    return [str(control), str(eff), str(center1)]


def _nm_is_active() -> Optional[bool]:
    """systemctl is-active NetworkManager, bounded; None if undeterminable."""
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "--quiet", "NetworkManager"],
            capture_output=True,
            timeout=3,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return res.returncode == 0


def _proc_running(proc: Optional["QProcess"]) -> bool:
    return proc is not None and proc.state() != QProcess.ProcessState.NotRunning


def _start_btn_css() -> str:
    return (
        f"QPushButton {{ background:{CAPTURE_BTN_START_BG}; color:{CAPTURE_BTN_START_FG}; border:none;"
        " border-radius:5px; font-size:11pt; font-weight:bold; }"
        f"QPushButton:hover {{ background:{CAPTURE_BTN_START_HOVER}; }}"
        f"QPushButton:disabled {{ background:{CAPTURE_BTN_DIS_BG}; color:{CAPTURE_BTN_DIS_FG}; }}"
    )


def _stop_btn_css() -> str:
    return (
        f"QPushButton {{ background:{CAPTURE_BTN_STOP_BG}; color:{CAPTURE_BTN_STOP_FG}; border:none;"
        " border-radius:5px; font-size:11pt; font-weight:bold; }"
        f"QPushButton:hover {{ background:{CAPTURE_BTN_STOP_HOVER}; }}"
        f"QPushButton:disabled {{ background:{CAPTURE_BTN_DIS_BG}; color:{CAPTURE_BTN_DIS_FG}; }}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Root scripts — FIXED TEXT.  Never .format() user values into these; every
# value is a positional argument ("$1", "$2", ...) supplied via QProcess args.
# ─────────────────────────────────────────────────────────────────────────────

# Shared bash function: stop tcpdump gracefully (SIGINT flushes the pcap),
# escalating to TERM/KILL.  Note: background jobs of a non-interactive bash
# start with SIGINT ignored unless the program re-arms it, hence the TERM step.
_BASH_STOP_TCPDUMP_FN = """\
stop_tcpdump() {
    local pid="$1" i
    kill -INT "$pid" 2>/dev/null || return 0
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.1
    done
    kill -TERM "$pid" 2>/dev/null || return 0
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.1
    done
    kill -KILL "$pid" 2>/dev/null || true
}
"""

_MONITOR_MASTER_SCRIPT = (
    """\
#!/bin/bash
# WaveScope monitor-mode capture (runs as root via pkexec).
#   $1 IFACE     managed WiFi interface to borrow
#   $2 OUTPUT    absolute pcap output path
#   $3 PID_FILE  tcpdump PID is recorded here for the cleanup script
#   $4 NM_MODE   unmanage (default) | stop (fallback: stop NetworkManager)
#   $5...        arguments for `iw dev mon0 set freq`
set -u
if [[ $# -lt 5 ]]; then
    echo "WAVESCOPE_SETUP_FAILED:args"
    exit 2
fi
IFACE="$1"
OUTPUT="$2"
PID_FILE="$3"
NM_MODE="$4"
shift 4
MON=mon0

NM_RESTORE=""     # managed | start | "" -- what teardown must undo
IFACE_DOWN=0
MON_CREATED=0
TDPID=""

"""
    + _BASH_STOP_TCPDUMP_FN
    + """
# ── TEARDOWN (always runs: normal end, error, or signal) ──────────────
teardown() {
    local rc=$?
    trap - EXIT INT TERM HUP PIPE
    trap '' PIPE    # the UI may be gone; never die while writing status
    if [[ -n "$TDPID" ]]; then
        stop_tcpdump "$TDPID"
        wait "$TDPID" 2>/dev/null
    fi
    rm -f -- "$PID_FILE"
    if [[ $MON_CREATED -eq 1 ]]; then
        ip link set "$MON" down 2>/dev/null
        iw dev "$MON" del || echo "WAVESCOPE_WARN:could not delete $MON"
    fi
    if [[ $IFACE_DOWN -eq 1 ]]; then
        ip link set "$IFACE" up || echo "WAVESCOPE_WARN:could not bring $IFACE up"
    fi
    case "$NM_RESTORE" in
        managed)
            nmcli device set "$IFACE" managed yes \\
                || echo "WAVESCOPE_WARN:nmcli could not re-manage $IFACE" ;;
        start)
            systemctl start NetworkManager \\
                || echo "WAVESCOPE_WARN:could not start NetworkManager" ;;
    esac
    echo "WAVESCOPE_TEARDOWN_OK"
    exit "$rc"
}
trap teardown EXIT INT TERM HUP PIPE

fail() {
    echo "WAVESCOPE_SETUP_FAILED:$1"
    exit 1
}

# ── SETUP (every step checked) ────────────────────────────────────────
case "$NM_MODE" in
    unmanage)
        # Only touch NM if it is running and currently manages the device
        if command -v nmcli >/dev/null 2>&1 \\
            && [[ "$(nmcli -t -f RUNNING general 2>/dev/null)" == "running" ]] \\
            && [[ "$(nmcli -g GENERAL.NM-MANAGED device show "$IFACE" 2>/dev/null)" == "yes" ]]; then
            NM_RESTORE=managed
            nmcli device set "$IFACE" managed no || fail nm_unmanage
            sleep 0.5    # let NM release the device before we reconfigure it
        fi ;;
    stop)
        if systemctl is-active --quiet NetworkManager; then
            NM_RESTORE=start
            systemctl stop NetworkManager || fail nm_stop
        fi ;;
    *)
        fail nm_mode ;;
esac

IFACE_DOWN=1
ip link set "$IFACE" down || fail iface_down
# Remove a stale mon0 left by a previous crashed run
if iw dev "$MON" info >/dev/null 2>&1; then
    iw dev "$MON" del || fail stale_mon_del
fi
iw dev "$IFACE" interface add "$MON" type monitor || fail interface_add
MON_CREATED=1
ip link set "$MON" up || fail mon_up
iw dev "$MON" set freq "$@" || fail set_freq

# ── CAPTURE ───────────────────────────────────────────────────────────
tcpdump -i "$MON" -e -nn -U -w "$OUTPUT" &
TDPID=$!
( set -C; echo "$TDPID" > "$PID_FILE" ) || fail pid_file
sleep 0.5
if ! kill -0 "$TDPID" 2>/dev/null; then
    wait "$TDPID" 2>/dev/null
    TDPID=""
    fail tcpdump
fi
echo "WAVESCOPE_SETUP_OK"
wait "$TDPID"
TDPID=""
rm -f -- "$PID_FILE"
echo "WAVESCOPE_CAPTURE_DONE"
exit 0
"""
)

_MANAGED_CAPTURE_SCRIPT = (
    """\
#!/bin/bash
# WaveScope managed-mode capture (runs as root via pkexec).
# WiFi stays connected; only this machine's traffic is captured.
#   $1 IFACE  $2 OUTPUT  $3 PID_FILE
set -u
if [[ $# -ne 3 ]]; then
    echo "WAVESCOPE_SETUP_FAILED:args"
    exit 2
fi
IFACE="$1"
OUTPUT="$2"
PID_FILE="$3"
TDPID=""

"""
    + _BASH_STOP_TCPDUMP_FN
    + """
teardown() {
    local rc=$?
    trap - EXIT INT TERM HUP PIPE
    trap '' PIPE
    if [[ -n "$TDPID" ]]; then
        stop_tcpdump "$TDPID"
        wait "$TDPID" 2>/dev/null
    fi
    rm -f -- "$PID_FILE"
    echo "WAVESCOPE_TEARDOWN_OK"
    exit "$rc"
}
trap teardown EXIT INT TERM HUP PIPE

fail() {
    echo "WAVESCOPE_SETUP_FAILED:$1"
    exit 1
}

tcpdump -i "$IFACE" -e -nn -U -w "$OUTPUT" &
TDPID=$!
( set -C; echo "$TDPID" > "$PID_FILE" ) || fail pid_file
sleep 0.5
if ! kill -0 "$TDPID" 2>/dev/null; then
    wait "$TDPID" 2>/dev/null
    TDPID=""
    fail tcpdump
fi
echo "WAVESCOPE_CAPTURE_OK"
wait "$TDPID"
TDPID=""
rm -f -- "$PID_FILE"
echo "WAVESCOPE_CAPTURE_DONE"
exit 0
"""
)

# Stop path for both modes: stop tcpdump (by PID file, as root).  tcpdump
# exiting ends the master script, whose EXIT trap performs the teardown.
_CLEANUP_SCRIPT = (
    """\
#!/bin/bash
# WaveScope capture stop (runs as root via pkexec).
#   $1 PID_FILE
set -u
if [[ $# -ne 1 ]]; then
    echo "WAVESCOPE_CLEANUP_BADARGS"
    exit 2
fi
PID_FILE="$1"

"""
    + _BASH_STOP_TCPDUMP_FN
    + """
if [[ -f "$PID_FILE" ]]; then
    TDPID="$(head -c 32 -- "$PID_FILE" 2>/dev/null | tr -cd '0-9')"
    # Only signal the PID if it really is tcpdump
    if [[ -n "$TDPID" && "$(cat "/proc/$TDPID/comm" 2>/dev/null)" == "tcpdump" ]]; then
        stop_tcpdump "$TDPID"
        echo "WAVESCOPE_CLEANUP_OK"
    else
        echo "WAVESCOPE_CLEANUP_NOPROC"
    fi
    rm -f -- "$PID_FILE"
else
    echo "WAVESCOPE_CLEANUP_NOPID"
fi
exit 0
"""
)


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

        _is_dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        _title_col = CAPTURE_TITLE_FG if _is_dark else "#1a2a3a"
        _note_col = FALLBACK_GRAY if _is_dark else "#555555"

        title = QLabel("Choose capture type")
        title.setStyleSheet(
            f"font-size:13pt; font-weight:bold; color:{_title_col};"
        )
        layout.addWidget(title)

        note = QLabel("Both modes require a root password prompt (pkexec / Polkit).")
        note.setStyleSheet(f"font-size:9pt; color:{_note_col};")
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


# ─────────────────────────────────────────────────────────────────────────────
# Shared capture-window base
# ─────────────────────────────────────────────────────────────────────────────


class _CaptureWindowBase(QDialog):
    """
    Shared pkexec orchestration for the capture windows.

    Lifecycle:  IDLE -> SETUP -> CAPTURE -> TEARDOWN -> IDLE
      * SETUP     master script launched, waiting for auth + ready marker.
                  Stop is disabled; a stop/close request is deferred.
      * CAPTURE   tcpdump running; Stop enabled.
      * TEARDOWN  cleanup script (root) stops tcpdump; the master's EXIT
                  trap restores the system; we return to IDLE only once the
                  master process has finished.

    Subclasses build the UI and must create: _iface_combo, _out_edit,
    _btn_start, _lbl_state, _lbl_elapsed, _lbl_size, _log (QPlainTextEdit).
    """

    _ST_IDLE = "idle"
    _ST_SETUP = "setup"
    _ST_CAPTURE = "capture"
    _ST_TEARDOWN = "teardown"

    # Per-subclass knobs
    _READY_MARKER = "WAVESCOPE_SETUP_OK"
    _SIZE_PREFIX = ""
    _MSG_READY: Tuple[str, ...] = ()
    _MSG_DONE = "✓  Capture complete."
    _MSG_TEARDOWN_OK = ""
    _CLOSE_PROMPT = (
        "A capture is running. Stop it and restore the interface before closing?"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self._ST_IDLE
        self._proc: Optional[QProcess] = None  # master pkexec script
        self._cleanup_proc: Optional[QProcess] = None  # stop script
        self._abandoned: List[QProcess] = []  # unkillable root procs, kept alive
        self._work_dir = ""  # private 0700 dir (mkdtemp)
        self._pid_file = ""
        self._cleanup_script = ""
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._start_time = 0.0
        self._iface_name = ""
        self._output_path = ""
        self._setup_error = ""  # step name from WAVESCOPE_SETUP_FAILED:<step>
        self._capture_done = False  # WAVESCOPE_CAPTURE_DONE seen
        self._stop_pending = False  # stop requested while still in SETUP
        self._close_after_stop = False  # close window once idle
        self._shutting_down = False  # inside shutdown_blocking(): no dialogs
        self._has_ifaces = True
        self._idle_label = "Idle"  # status text once back to IDLE

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        # Last-resort watchdog: armed only after cleanup succeeded
        self._force_timer = QTimer(self)
        self._force_timer.setSingleShot(True)
        self._force_timer.setInterval(_FORCE_KILL_GRACE_MS)
        self._force_timer.timeout.connect(self._force_kill)

    # ── Public API (used by the main window on application exit) ─────────

    def is_busy(self) -> bool:
        """
        True while a capture, its setup or its teardown is in progress,
        i.e. while root-side state (monitor interface, NetworkManager
        unmanaged/stopped, tcpdump) may still need restoring.
        """
        return (
            self._state != self._ST_IDLE
            or _proc_running(self._proc)
            or _proc_running(self._cleanup_proc)
        )

    def shutdown_blocking(self, timeout_ms: int = 15000) -> None:
        """
        Synchronously stop any capture so the system is restored before
        the application exits.  Blocks the calling (GUI) thread for at most
        roughly *timeout_ms* milliseconds (+ ~2 s for a force-kill attempt).

        Steps: wait for an in-progress SETUP to finish or fail; run the
        cleanup script via pkexec (the user may get a Polkit prompt) and
        wait for it with QProcess.waitForFinished; then wait for the master
        script, whose EXIT trap restores the interface and NetworkManager.
        If the master is still running at the deadline it is force-killed
        and the manual sudo cleanup commands are logged and printed to
        stderr.  No message boxes are shown.  Safe to call when idle.
        """
        self._shutting_down = True
        self._close_after_stop = False
        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0

        def remaining() -> int:
            return max(0, int((deadline - time.monotonic()) * 1000))

        if _proc_running(self._proc):
            # 1. Let SETUP complete; the ready marker then triggers the stop
            self._stop_pending = True
            while (
                self._state == self._ST_SETUP
                and _proc_running(self._proc)
                and remaining() > 0
            ):
                # waitForReadyRead delivers readyRead/finished synchronously
                self._proc.waitForReadyRead(min(250, remaining()))

            # 2. Request the stop if nothing has done so yet
            if self._state == self._ST_CAPTURE and self._cleanup_proc is None:
                self._begin_stop()

            # 3. Wait for the root cleanup script
            if _proc_running(self._cleanup_proc) and remaining() > 0:
                self._cleanup_proc.waitForFinished(remaining())

            # 4. Wait for the master's EXIT-trap teardown
            if _proc_running(self._proc) and remaining() > 0:
                self._proc.waitForFinished(remaining())

            # 5. Last resort
            if _proc_running(self._proc):
                self._force_kill()

        if _proc_running(self._cleanup_proc):
            # pkexec still waiting for auth (killable) or finishing as root
            self._cleanup_proc.kill()
            self._cleanup_proc.waitForFinished(1000)
        self._maybe_finish()
        self._remove_work_dir()

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _config_widgets(self) -> List[QWidget]:
        """Widgets enabled only while idle."""
        return []

    def _manual_cleanup_commands(self) -> List[str]:
        """Shell commands (for the user, via sudo) to undo root-side state."""
        pid = self._read_pid()
        if pid is not None:
            return [f"sudo kill -INT {pid}"]
        return ["sudo pkill -INT -x tcpdump"]

    # ── Shared UI helpers ─────────────────────────────────────────────────

    def _populate_interfaces(self):
        ifaces = _detect_wifi_interfaces()
        self._iface_combo.clear()
        self._has_ifaces = bool(ifaces)
        if not ifaces:
            self._iface_combo.addItem("No WiFi interfaces found")
            self._btn_start.setEnabled(False)
            return
        for ifc in ifaces:
            label = ifc["name"]
            if ifc["connected_ssid"]:
                label += f"  (connected: {ifc['connected_ssid']})"
            self._iface_combo.addItem(label, ifc["name"])

    def _set_state(self, state: str, label: str):
        self._state = state
        self._lbl_state.setText(label)
        idle = state == self._ST_IDLE
        for w in self._config_widgets():
            w.setEnabled(idle)
        btn = self._btn_start
        if idle:
            btn.setText("▶  Start Capture")
            btn.setStyleSheet(_start_btn_css())
            btn.setEnabled(self._has_ifaces)
        elif state == self._ST_SETUP:
            # Stop is disabled until the ready marker: stopping mid-setup
            # would race the master script's own setup/teardown.
            btn.setText("⏳  Setting up…")
            btn.setStyleSheet(_stop_btn_css())
            btn.setEnabled(False)
        elif state == self._ST_CAPTURE:
            btn.setText("⏹  Stop Capture")
            btn.setStyleSheet(_stop_btn_css())
            btn.setEnabled(True)
        else:  # TEARDOWN
            btn.setText("⏳  Stopping…")
            btn.setStyleSheet(_stop_btn_css())
            btn.setEnabled(False)

    def _tick(self):
        elapsed = int(time.monotonic() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._lbl_elapsed.setText(f"{m:02d}:{s:02d}")
        try:
            sz = os.path.getsize(self._output_path)
            if sz < 1024 * 1024:
                self._lbl_size.setText(f"{self._SIZE_PREFIX}{sz / 1024:.1f} KB")
            else:
                self._lbl_size.setText(f"{self._SIZE_PREFIX}{sz / 1024 / 1024:.2f} MB")
        except OSError:
            self._lbl_size.setText(f"{self._SIZE_PREFIX}—")

    def _log_line(self, text: str):
        self._log.appendPlainText(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _show_error(self, title: str, text: str):
        """Log an error and, unless shutting down, show it in a dialog."""
        self._log_line(f"✗  {text}")
        if not self._shutting_down:
            QMessageBox.warning(self, title, text)

    def _log_saved_size(self):
        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(f"\U0001f4c1  Saved {sz / 1024:.1f} KB → {self._output_path}")
        except OSError:
            pass

    # ── Temp dir / process plumbing ───────────────────────────────────────

    def _make_process(self) -> QProcess:
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        return p

    def _write_script(self, name: str, body: str) -> str:
        """Write *body* into the private work dir as an 0700 script."""
        path = os.path.join(self._work_dir, name)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRWXU)
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        return path

    def _prepare_work_dir(self, master_body: str) -> Optional[str]:
        """
        Create the per-capture private dir (0700) with the master and
        cleanup scripts.  Returns the master script path, or None on error.
        """
        self._remove_work_dir()
        try:
            self._work_dir = tempfile.mkdtemp(prefix="wavescope_cap_")  # 0700
            self._pid_file = os.path.join(self._work_dir, "tcpdump.pid")
            master = self._write_script("capture.sh", master_body)
            self._cleanup_script = self._write_script("stop.sh", _CLEANUP_SCRIPT)
        except OSError as exc:
            self._remove_work_dir()
            self._show_error("Capture failed", f"Could not create temp files: {exc}")
            return None
        return master

    def _remove_work_dir(self):
        # May contain a root-owned PID file; the dir is ours, so unlink works.
        if self._work_dir:
            shutil.rmtree(self._work_dir, ignore_errors=True)
        self._work_dir = ""
        self._pid_file = ""
        self._cleanup_script = ""

    def _read_pid(self) -> Optional[int]:
        try:
            with open(self._pid_file, encoding="ascii", errors="ignore") as fh:
                txt = fh.read(32).strip()
            return int(txt) if txt.isdigit() else None
        except (OSError, ValueError):
            return None

    def _start_master(self, script: str, args: List[str]):
        """Launch `pkexec bash <script> <args...>` — args are never parsed by a shell."""
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._setup_error = ""
        self._capture_done = False
        self._stop_pending = False
        self._lbl_elapsed.setText("00:00")
        self._set_state(self._ST_SETUP, "Waiting for authentication…")

        proc = self._make_process()
        proc.readyReadStandardOutput.connect(lambda p=proc: self._on_master_stdout(p))
        proc.readyReadStandardError.connect(lambda p=proc: self._on_master_stderr(p))
        proc.finished.connect(
            lambda code, status, p=proc: self._on_master_finished(p, code, status)
        )
        self._proc = proc
        proc.start(PKEXEC_BIN, ["bash", script, *args])
        self._log_line("▶  Starting (Polkit authentication may appear…)")

    # ── Master output handling ────────────────────────────────────────────

    def _on_master_stdout(self, proc: QProcess):
        if proc is not self._proc:
            return
        self._stdout_buf += bytes(proc.readAllStandardOutput()).decode(errors="replace")
        self._drain_stdout(final=False)

    def _on_master_stderr(self, proc: QProcess):
        if proc is not self._proc:
            return
        self._stderr_buf += bytes(proc.readAllStandardError()).decode(errors="replace")
        self._drain_stderr(final=False)

    def _drain_stdout(self, final: bool):
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            self._handle_master_line(line.strip())
        if final:
            if self._stdout_buf.strip():
                self._handle_master_line(self._stdout_buf.strip())
            self._stdout_buf = ""

    def _drain_stderr(self, final: bool):
        while "\n" in self._stderr_buf:
            line, self._stderr_buf = self._stderr_buf.split("\n", 1)
            if line.strip():
                self._log_line(f"  {line.strip()}")
        if final:
            if self._stderr_buf.strip():
                self._log_line(f"  {self._stderr_buf.strip()}")
            self._stderr_buf = ""

    def _handle_master_line(self, line: str):
        if not line:
            return
        if line == self._READY_MARKER:
            self._on_ready()
        elif line.startswith("WAVESCOPE_SETUP_FAILED:"):
            self._setup_error = line.split(":", 1)[1] or "unknown"
            self._log_line(f"✗  Setup failed at step: {self._setup_error}")
        elif line == "WAVESCOPE_CAPTURE_DONE":
            self._capture_done = True
            self._timer.stop()
            if self._state != self._ST_IDLE:
                self._set_state(self._ST_TEARDOWN, "Restoring…")
            self._log_line(self._MSG_DONE)
        elif line == "WAVESCOPE_TEARDOWN_OK":
            if self._MSG_TEARDOWN_OK:
                self._log_line(self._MSG_TEARDOWN_OK)
        elif line.startswith("WAVESCOPE_WARN:"):
            self._log_line(f"⚠  {line.split(':', 1)[1]}")
        else:
            self._log_line(f"  {line}")

    def _on_ready(self):
        self._set_state(self._ST_CAPTURE, "Capturing…")
        self._start_time = time.monotonic()
        self._timer.start()
        for msg in self._MSG_READY:
            self._log_line(msg)
        if self._stop_pending:
            # A stop/close arrived during SETUP — honour it now
            self._stop_pending = False
            self._begin_stop()

    def _on_master_finished(self, proc: QProcess, exit_code: int, exit_status):
        if proc is not self._proc:
            return
        self._timer.stop()
        self._force_timer.stop()
        self._stdout_buf += bytes(proc.readAllStandardOutput()).decode(errors="replace")
        self._stderr_buf += bytes(proc.readAllStandardError()).decode(errors="replace")
        self._drain_stdout(final=True)
        self._drain_stderr(final=True)

        crashed = exit_status == QProcess.ExitStatus.CrashExit
        self._idle_label = (
            "Idle \u2014 capture complete"
            if self._state != self._ST_SETUP and not self._setup_error
            else "Idle \u2014 capture not started"
        )
        if self._setup_error:
            self._show_error(
                "Capture setup failed",
                f"Setup failed at step '{self._setup_error}' (exit {exit_code}). "
                "Changes made so far were rolled back; see the log for details.",
            )
        elif self._state == self._ST_SETUP:
            if not crashed and exit_code in _PKEXEC_AUTH_EXIT:
                self._log_line("✗  Authentication cancelled or not authorized.")
            else:
                self._show_error(
                    "Capture failed",
                    f"The capture process exited (code {exit_code}) before setup "
                    "completed. Check that pkexec, iw and tcpdump are installed.",
                )
        elif crashed:
            self._log_line("⚠  Capture process was killed.")
        elif exit_code != 0:
            self._log_line(f"⚠  Capture process exited with code {exit_code}.")

        self._proc = None
        proc.deleteLater()
        self._log_saved_size()
        if _proc_running(self._cleanup_proc):
            # Master is gone; a cleanup still waiting for auth is pointless.
            # (If it already runs as root the kill is a no-op and it ends soon.)
            self._cleanup_proc.kill()
        self._maybe_finish()

    def _maybe_finish(self):
        """Return to IDLE once neither the master nor cleanup is running."""
        if _proc_running(self._proc) or _proc_running(self._cleanup_proc):
            return
        self._timer.stop()
        self._force_timer.stop()
        self._remove_work_dir()
        self._stop_pending = False
        if self._state != self._ST_IDLE:
            self._set_state(self._ST_IDLE, self._idle_label)
        if self._close_after_stop and not self._shutting_down:
            self._close_after_stop = False
            QTimer.singleShot(0, self.close)

    # ── Stop flow ─────────────────────────────────────────────────────────

    def _on_start_stop(self):
        if self._state == self._ST_IDLE:
            self._start_capture()
        else:
            self._request_stop()

    def _start_capture(self):
        raise NotImplementedError

    def _request_stop(self):
        if self._state == self._ST_SETUP:
            if not self._stop_pending:
                self._stop_pending = True
                self._log_line("⏹  Stop requested — waiting for setup to finish…")
            return
        if self._state == self._ST_CAPTURE:
            self._begin_stop()

    def _begin_stop(self):
        """Run the root cleanup script, which stops tcpdump via its PID file."""
        if not _proc_running(self._proc) or self._cleanup_proc is not None:
            return
        if not self._cleanup_script or not os.path.exists(self._cleanup_script):
            self._log_line("⚠  Cleanup script missing — cannot stop cleanly.")
            self._force_kill()
            return
        self._set_state(self._ST_TEARDOWN, "Stopping…")
        self._log_line(
            "⏹  Stopping — launching cleanup (a password prompt may appear)…"
        )
        proc = self._make_process()
        proc.readyReadStandardOutput.connect(lambda p=proc: self._on_cleanup_output(p))
        proc.readyReadStandardError.connect(lambda p=proc: self._on_cleanup_output(p))
        proc.finished.connect(
            lambda code, status, p=proc: self._on_cleanup_finished(p, code, status)
        )
        self._cleanup_proc = proc
        proc.start(PKEXEC_BIN, ["bash", self._cleanup_script, self._pid_file])

    def _on_cleanup_output(self, proc: QProcess):
        data = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        data += bytes(proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            ln = line.strip()
            if ln == "WAVESCOPE_CLEANUP_OK":
                self._log_line("✓  tcpdump stopped — restoring…")
            elif ln in ("WAVESCOPE_CLEANUP_NOPID", "WAVESCOPE_CLEANUP_NOPROC"):
                self._log_line("  tcpdump was not running (nothing to stop).")
            elif ln:
                self._log_line(f"  {ln}")

    def _on_cleanup_finished(self, proc: QProcess, exit_code: int, exit_status):
        if proc is not self._cleanup_proc:
            return
        self._on_cleanup_output(proc)
        self._cleanup_proc = None
        proc.deleteLater()
        ok = exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        master_running = _proc_running(self._proc)
        if ok:
            if master_running:
                # Master should now run its EXIT trap; watchdog just in case
                self._force_timer.start()
        else:
            if exit_code in _PKEXEC_AUTH_EXIT:
                self._log_line("⚠  Stop authentication cancelled.")
            else:
                self._log_line(f"⚠  Cleanup exited with code {exit_code}.")
            if master_running and self._state == self._ST_TEARDOWN and not self._capture_done:
                # Capture is still live: let the user try Stop again
                self._close_after_stop = False
                self._set_state(self._ST_CAPTURE, "Capturing…")
                self._log_line("  Capture is still running — press Stop to retry.")
        self._maybe_finish()

    def _force_kill(self):
        """
        Last resort.  QProcess.kill() only reaches pkexec before it has
        exec'd the root bash; afterwards SIGKILL from our uid gets EPERM.
        So always tell the user how to clean up manually.
        """
        proc = self._proc
        if not _proc_running(proc):
            return
        cmds = self._manual_cleanup_commands()
        self._log_line("⚠  Capture process did not exit — force-killing it.")
        self._log_line("⚠  Manual cleanup may be needed. Run these in a terminal:")
        for c in cmds:
            self._log_line(f"      {c}")
        print(
            "WaveScope: capture did not stop cleanly; manual cleanup may be "
            "needed:\n" + "\n".join(f"  {c}" for c in cmds),
            file=sys.stderr,
        )
        proc.kill()
        if proc.waitForFinished(2000):
            return  # finished handler already ran
        # Unkillable (root) process: stop tracking it so the UI can recover
        for sig in (proc.readyReadStandardOutput, proc.readyReadStandardError, proc.finished):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self._abandoned.append(proc)
        self._proc = None
        self._log_line("⚠  Gave up waiting for the capture process.")
        self._maybe_finish()

    # ── Qt events ─────────────────────────────────────────────────────────

    def reject(self):
        # Esc would otherwise just hide the dialog with a capture still live
        if self.is_busy():
            self.close()
        else:
            super().reject()

    def closeEvent(self, event):
        if not self.is_busy() or self._shutting_down:
            event.accept()
            return
        if self._close_after_stop:
            event.ignore()  # already stopping; we close ourselves when idle
            return
        r = QMessageBox.question(
            self,
            "Capture in progress",
            self._CLOSE_PROMPT,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            # During SETUP this defers the stop until setup finishes/fails;
            # the window closes from _maybe_finish() once teardown is done.
            self._close_after_stop = True
            self._request_stop()
            if not self.is_busy():
                event.accept()
                return
        event.ignore()


# ─────────────────────────────────────────────────────────────────────────────
# Monitor-mode capture window
# ─────────────────────────────────────────────────────────────────────────────


class MonitorModeWindow(_CaptureWindowBase):
    """
    Packet-capture window using a temporary monitor-mode interface (mon0).
    Requires root via pkexec / Polkit.
    """

    _READY_MARKER = "WAVESCOPE_SETUP_OK"
    _SIZE_PREFIX = ""
    _MSG_READY = (
        f"✓  Monitor interface {_MON_IFACE} ready.",
        "▶  tcpdump running — click Stop to end capture.",
    )
    _MSG_DONE = "▶  Restoring interface and NetworkManager…"
    _MSG_TEARDOWN_OK = "✓  Interface and NetworkManager restored."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📡  Monitor Mode  —  Packet Capture")
        self.setMinimumSize(620, 680)
        self.setModal(False)
        self._nm_mode = "unmanage"

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
        cfg_layout.addRow("Interface:", self._iface_combo)

        self._band_sel = QComboBox()
        self._band_sel.addItems(list(_BAND_CHANNELS))
        self._band_sel.currentTextChanged.connect(self._on_band_sel)
        cfg_layout.addRow("Band:", self._band_sel)

        self._chan_combo = QComboBox()
        self._chan_combo.setMinimumWidth(180)
        cfg_layout.addRow("Channel:", self._chan_combo)

        # Channel width: invalid combos fall back to 20 MHz at start
        self._width_combo = QComboBox()
        for w in _WIDTHS:
            self._width_combo.addItem(f"{w} MHz", w)
        self._width_combo.setCurrentIndex(0)
        cfg_layout.addRow("Width:", self._width_combo)

        # NetworkManager handling: default = unmanage just this device
        self._chk_stop_nm = QCheckBox("Stop NetworkManager entirely (fallback)")
        self._chk_stop_nm.setToolTip(
            "By default only the selected interface is released from\n"
            "NetworkManager (nmcli device set <iface> managed no) and handed\n"
            "back afterwards. Enable this only if NetworkManager still\n"
            "interferes with the monitor interface."
        )
        cfg_layout.addRow("", self._chk_stop_nm)

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
        self._btn_browse = QPushButton("Browse…")
        self._btn_browse.setMaximumWidth(80)
        self._btn_browse.clicked.connect(self._on_browse)
        out_hl.addWidget(self._btn_browse)
        cfg_layout.addRow("Output file:", out_row)

        layout.addWidget(cfg)

        # ── Start / Stop button ───────────────────────────────────────────
        self._btn_start = QPushButton("▶  Start Capture")
        self._btn_start.setMinimumHeight(38)
        self._btn_start.setStyleSheet(_start_btn_css())
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

    def _config_widgets(self) -> List[QWidget]:
        return [
            self._iface_combo,
            self._band_sel,
            self._chan_combo,
            self._width_combo,
            self._chk_stop_nm,
            self._out_edit,
            self._btn_browse,
        ]

    # ── Populate helpers ──────────────────────────────────────────────────

    def _on_band_sel(self, band: str):
        self._chan_combo.clear()
        src = _BAND_CHANNELS.get(band, CH24)
        for ch, freq in sorted(src.items(), key=lambda x: x[1]):
            self._chan_combo.addItem(f"Ch {ch}  ({freq} MHz)", ch)

    def _on_browse(self):
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

    def _start_capture(self):
        if self._state != self._ST_IDLE:
            return
        iface = self._iface_combo.currentData()
        if not _valid_iface(iface):
            self._show_error("Invalid interface", f"Invalid interface name: {iface!r}")
            return
        band = self._band_sel.currentText()
        channel = self._chan_combo.currentData()
        if not isinstance(channel, int) or channel not in _BAND_CHANNELS.get(band, {}):
            self._show_error("Invalid channel", f"Invalid channel for {band}: {channel!r}")
            return
        width = self._width_combo.currentData()
        width = width if isinstance(width, int) else 20
        output, err = _validate_output_path(self._out_edit.text().strip())
        if output is None:
            self._show_error("Invalid output file", err)
            return
        self._out_edit.setText(output)

        eff_width = _effective_width(channel, band, width)
        freq_args = _iw_freq_args(channel, band, width)
        self._iface_name = iface
        self._output_path = output
        self._nm_mode = "stop" if self._chk_stop_nm.isChecked() else "unmanage"

        self._log_line(f"Interface : {iface}")
        self._log_line(f"Band/Chan : {band}  ch {channel}")
        if eff_width != width:
            self._log_line(
                f"Width     : {width} MHz not valid for ch {channel} — falling back to 20 MHz"
            )
        else:
            self._log_line(f"Width     : {eff_width} MHz")
        self._log_line(f"Tune      : iw dev {_MON_IFACE} set freq {' '.join(freq_args)}")
        self._log_line(f"Output    : {output}")
        if self._nm_mode == "stop":
            nm = _nm_is_active()
            state = "unknown" if nm is None else ("yes" if nm else "no")
            self._log_line(f"NM        : will be stopped (active now: {state})")
        else:
            self._log_line(f"NM        : {iface} set unmanaged during capture")
        self._log_line("─" * 50)

        script = self._prepare_work_dir(_MONITOR_MASTER_SCRIPT)
        if script is None:
            return
        self._start_master(
            script, [iface, output, self._pid_file, self._nm_mode, *freq_args]
        )

    def _manual_cleanup_commands(self) -> List[str]:
        iface = shlex.quote(self._iface_name or "wlan0")
        cmds = super()._manual_cleanup_commands()
        cmds += [
            f"sudo iw dev {_MON_IFACE} del",
            f"sudo ip link set {iface} up",
        ]
        if self._nm_mode == "stop":
            cmds.append("sudo systemctl start NetworkManager")
        else:
            cmds.append(f"sudo nmcli device set {iface} managed yes")
        return cmds


# ─────────────────────────────────────────────────────────────────────────────
# Managed-mode capture window
# ─────────────────────────────────────────────────────────────────────────────


class ManagedCaptureWindow(_CaptureWindowBase):
    """
    Managed-mode packet capture — WiFi stays connected.
    Only captures traffic to/from this machine. Requires root via pkexec.
    """

    _READY_MARKER = "WAVESCOPE_CAPTURE_OK"
    _SIZE_PREFIX = "File:  "
    _MSG_READY = (
        "✓  tcpdump running — WiFi connection is intact.",
        "▶  Click Stop to end capture.",
    )
    _MSG_DONE = "✓  Capture complete."
    _MSG_TEARDOWN_OK = ""
    _CLOSE_PROMPT = "A capture is running. Stop it before closing?"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f310  Managed Capture  —  Packet Capture")
        self.setMinimumSize(560, 540)
        self.setModal(False)

        self._build_ui()
        self._populate_interfaces()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        banner = QLabel(
            "ℹ  Your WiFi connection stays active. Only traffic to/from "
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
            os.path.join(self._default_dir(), f"managed_{int(time.time())}.pcap")
        )
        self._btn_browse = QPushButton("Browse…")
        self._btn_browse.setFixedWidth(80)
        self._btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(self._btn_browse)
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

        # Plain text: root stderr must never be interpreted as rich text
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setStyleSheet(
            f"background:{CAPTURE_MGD_LOG_BG}; color:{CAPTURE_MGD_LOG_FG}; font-family:monospace;"
            " font-size:9pt; border-radius:4px;"
        )
        layout.addWidget(self._log, 1)

        self._btn_start = QPushButton("▶  Start Capture")
        self._btn_start.setMinimumHeight(42)
        self._btn_start.setStyleSheet(_start_btn_css())
        self._btn_start.clicked.connect(self._on_start_stop)
        layout.addWidget(self._btn_start)

    @staticmethod
    def _default_dir() -> str:
        desktop = os.path.expanduser("~/Desktop")
        return desktop if os.path.isdir(desktop) else os.path.expanduser("~")

    def _config_widgets(self) -> List[QWidget]:
        return [self._iface_combo, self._out_edit, self._btn_browse]

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Capture File",
            self._default_dir(),
            "PCAP files (*.pcap);;All files (*)",
        )
        if path:
            self._out_edit.setText(path)

    # ── Capture lifecycle ─────────────────────────────────────────────────

    def _start_capture(self):
        if self._state != self._ST_IDLE:
            return
        iface = (
            self._iface_combo.currentData() or self._iface_combo.currentText()
        ).strip()
        if not _valid_iface(iface):
            self._show_error("Invalid interface", f"Select a valid WiFi interface (got {iface!r}).")
            return
        output, err = _validate_output_path(self._out_edit.text().strip())
        if output is None:
            self._show_error("Invalid output file", err)
            return
        self._out_edit.setText(output)
        self._iface_name = iface
        self._output_path = output
        self._log.clear()
        self._log_line(f"Interface : {iface}")
        self._log_line(f"Output    : {output}")
        self._log_line("─" * 50)

        script = self._prepare_work_dir(_MANAGED_CAPTURE_SCRIPT)
        if script is None:
            return
        self._start_master(script, [iface, output, self._pid_file])


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
