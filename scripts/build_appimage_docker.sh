#!/usr/bin/env bash
# build_appimage_docker.sh — Build the WaveScope AppImage inside Docker
# (Ubuntu 22.04, same base as the release CI), so the host needs neither
# appimagetool nor a matching Python.  Output lands in the repo root.
#
# Usage: ./scripts/build_appimage_docker.sh [version]
# Requires: docker (usable by the current user)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="wavescope-appimage-builder:22.04"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker not found"
    exit 1
fi

echo "▸ Building builder image ($IMAGE)…"
docker build -t "$IMAGE" -f "$SCRIPT_DIR/docker/appimage-builder.Dockerfile" "$SCRIPT_DIR/docker"

# Run as the calling user so the AppImage and build dir are not root-owned.
# HOME points at a writable scratch dir for pip's cache.
echo "▸ Running AppImage build in container…"
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$REPO_ROOT:/work" \
    -w /work \
    "$IMAGE" \
    ./scripts/build_appimage.sh "$@"
