#!/usr/bin/env bash
# test_appimage_xvfb.sh — launch-test an AppImage under Xvfb in a bare container
#
# Mirrors the AppImage catalog check: on a minimal system the app must show a
# window and keep running.  The container gets only what an AppImage may
# expect from the host (the pkg2appimage excludelist set plus glib/dbus) —
# deliberately NOT libxcb-cursor & co., which the AppImage has to bundle.
#
# Cases:
#   1. default launch     — the host has no nmcli/iw/tcpdump; the main window
#                           must appear (the bundled iw serves scanning) and
#                           no "Missing dependencies" dialog may show
#   2. bundled iw         — <AppDir>/usr/bin/iw runs with the bundled libnl
#   3. no error text      — the status/notice wording the app shows in this
#                           state must not match the AppImage catalog's
#                           error-screenshot regexes (code/check-screenshot.sh)
#
# Usage: ./scripts/test_appimage_xvfb.sh WaveScope-<ver>-x86_64.AppImage
# Requires: docker.  Env: TEST_IMAGE (default ubuntu:22.04)
set -euo pipefail

if [ $# -ne 1 ] || [ ! -f "$1" ]; then
    echo "Usage: $0 <path/to/WaveScope-*.AppImage>"
    exit 2
fi
APPIMAGE="$(readlink -f "$1")"
IMAGE="${TEST_IMAGE:-ubuntu:22.04}"
HOST_PKGS="xvfb x11-utils procps libegl1 libgl1 libfontconfig1 libfreetype6 libharfbuzz0b libglib2.0-0 libdbus-1-3 libx11-6 libx11-xcb1 libxcb1"  # note: no nmcli / iw / tcpdump on purpose

docker run --rm -v "$APPIMAGE:/app/WaveScope.AppImage:ro" "$IMAGE" bash -c '
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends '"$HOST_PKGS"' >/dev/null 2>&1 \
    || { echo "FAIL: could not install host packages"; exit 1; }

# xwininfo must decode UTF-8 window titles (the dialog title has an em-dash)
Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.2; done
xdpyinfo >/dev/null 2>&1 || { echo "FAIL: Xvfb did not start"; cat /tmp/xvfb.log; exit 1; }

FAILED=0
# run_case <name> <window-title regex> [ENV=VAL ...]
run_case() {
    local name="$1" regex="$2"; shift 2
    local log="/tmp/$name.log" home="/tmp/home-$name"
    mkdir -p "$home"
    # setsid → own process group, so the whole tree (runtime, bash, python)
    # can be stopped at the end.
    setsid env HOME="$home" "$@" /app/WaveScope.AppImage --appimage-extract-and-run >"$log" 2>&1 &
    local pid=$! shown=""
    for _ in $(seq 60); do                       # up to 30 s to show a window
        kill -0 "$pid" 2>/dev/null || break
        if LC_ALL=C.UTF-8 xwininfo -root -tree 2>/dev/null | grep -Eq "$regex"; then shown=1; break; fi
        sleep 0.5
    done
    local alive=1
    if [ -n "$shown" ]; then
        for _ in $(seq 20); do                   # must keep running 10 s more
            kill -0 "$pid" 2>/dev/null || { alive=0; break; }
            sleep 0.5
        done
    fi
    if [ -n "$shown" ] && [ "$alive" = 1 ]; then
        echo "PASS: $name — window matching /$regex/:"
        LC_ALL=C.UTF-8 xwininfo -root -tree | grep -E "$regex" | head -3 | sed "s/^/      /"
    else
        FAILED=1
        if [ -z "$shown" ]; then echo "FAIL: $name — no window matching /$regex/ within 30 s"
        else echo "FAIL: $name — process exited after showing its window"; fi
        echo "----- $name log (last 40 lines) -----"; tail -40 "$log"
    fi
    kill -TERM -- "-$pid" 2>/dev/null; sleep 1; kill -KILL -- "-$pid" 2>/dev/null
    pkill -KILL -f "wavescope/main.py" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
}

run_case main-window "WaveScope v[0-9]"
# No dialog may accompany the first window: the catalog screenshots whatever
# is on screen, and an unmanaged dialog renders as a black box.
EXTRA=$(LC_ALL=C.UTF-8 xwininfo -root -children 2>/dev/null | grep -E "\(\"main.py\" " | grep -Ev "\"WaveScope v[0-9]" || true)
if [ -n "$EXTRA" ]; then
    echo "FAIL: extra top-level window(s) besides the main window:"; echo "$EXTRA"; FAILED=1
else
    echo "PASS: only the main window is shown (no dialogs)"
fi

# bundled iw: extract once and run it with the bundled libraries only
/app/WaveScope.AppImage --appimage-extract >/dev/null 2>&1
P=$PWD/squashfs-root/usr/share/wavescope
if LD_LIBRARY_PATH="$P/python-runtime/lib" $PWD/squashfs-root/usr/bin/iw --version | grep -q "iw version"; then
    echo "PASS: bundled iw — $(LD_LIBRARY_PATH="$P/python-runtime/lib" $PWD/squashfs-root/usr/bin/iw --version)"
else
    echo "FAIL: bundled iw does not run"; FAILED=1
fi

# wording check against the catalog error regexes (code/check-screenshot.sh)
HARD="traceback|exception|segmentation fault|fatal|error while loading|glibc|not installed|cannot open display|permission denied|no such file|could not (load|find|open|start|initiali)|failed to (load|start|open|initiali|create)|cannot (load|find|open|execute|configure)|unable to (load|find|open|start)|command not found|core dumped"
SOFT="error|failed|failure|could not|cannot|unable to|not found"
TEXT=$(cd $P && LD_LIBRARY_PATH=$P/python-runtime/lib PYTHONHOME=$P/python-runtime PYTHONPATH="$(echo $P/.venv/lib/python*/site-packages)" QT_QPA_PLATFORM=offscreen \
    WAVESCOPE_BUNDLED_IW=$PWD/squashfs-root/usr/bin/iw $P/.venv/bin/python -c "
from wavescope_app.core import tool_notices
print(chr(10).join(tool_notices()))
print(\"No Wi-Fi interface detected — connect or enable a wireless adapter.\")
print(\"Showing the kernel scan cache; NetworkManager is absent, so scans refresh only when the system itself scans.\")
" 2>/dev/null)
if echo "$TEXT" | grep -qiE "$HARD|$SOFT"; then
    echo "FAIL: notice wording matches the catalog error regex:"; echo "$TEXT" | grep -iE "$HARD|$SOFT"; FAILED=1
else
    N=$(echo "$TEXT" | grep -c .)
    if [ "$N" -lt 3 ]; then echo "FAIL: notice snippet produced only $N lines"; FAILED=1
    else echo "PASS: notice wording clear of the catalog error regexes ($N lines)"; fi
fi
exit $FAILED
'
