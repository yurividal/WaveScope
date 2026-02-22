#!/usr/bin/env bash
# build_appimage_docker.sh — Build WaveScope AppImage inside Docker
# Usage: ./build_appimage_docker.sh [version]
set -euo pipefail

VERSION="${1:-}"
IMAGE_NAME="wavescope-appimage-builder:latest"
DOCKERFILE="scripts/docker/appimage-builder.Dockerfile"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker not found. Install Docker/Podman first."
    exit 1
fi

if [ ! -f "$DOCKERFILE" ]; then
    echo "ERROR: missing Dockerfile: $DOCKERFILE"
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Docker image for AppImage toolchain"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker build -f "$DOCKERFILE" -t "$IMAGE_NAME" .

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building WaveScope AppImage inside Docker"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -n "$VERSION" ]; then
    docker run --rm \
        -u "$(id -u):$(id -g)" \
        -v "$PWD:/work" \
        -w /work \
        "$IMAGE_NAME" \
        bash -lc "./scripts/build_appimage.sh '$VERSION'"
else
    docker run --rm \
        -u "$(id -u):$(id -g)" \
        -v "$PWD:/work" \
        -w /work \
        "$IMAGE_NAME" \
        bash -lc "./scripts/build_appimage.sh"
fi

echo ""
echo "✓ Done. AppImage is in the project root."
