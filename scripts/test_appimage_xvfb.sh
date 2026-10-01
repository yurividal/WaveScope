#!/usr/bin/env bash
# test_appimage_xvfb.sh — launch-test an AppImage under Xvfb in a bare container
#
# Mirrors the AppImage catalog check: on a minimal system the app must show a
# window and keep running.  The container gets only what an AppImage may
# expect from the host (the pkg2appimage excludelist set plus glib/dbus) —
# deliberately NOT libxcb-cursor & co., which the AppImage has to bundle.
#
# Two cases:
#   1. default launch     — nmcli/iw are absent, so the "Missing dependencies"
#                           dialog must appear (this is what the catalog sees)
#   2. main window        — WAVESCOPE_SKIP_DEPENDENCY_CHECK=1; the main window
#                           must appear and survive startup + first scan cycle
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
HOST_PKGS="xvfb x11-utils procps libegl1 libgl1 libfontconfig1 libfreetype6 libharfbuzz0b libglib2.0-0 libdbus-1-3 libx11-6 libx11-xcb1 libxcb1"

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

run_case default-launch "WaveScope.*[Mm]issing dependencies"
run_case main-window    "WaveScope v[0-9]" WAVESCOPE_SKIP_DEPENDENCY_CHECK=1
exit $FAILED
'
