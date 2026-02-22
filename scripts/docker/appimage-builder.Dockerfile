FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    python3 \
    python3-venv \
    python3-pip \
    wget \
    xz-utils \
    file \
    desktop-file-utils \
    libglib2.0-bin \
    && rm -rf /var/lib/apt/lists/*

RUN wget -qO /opt/appimagetool.AppImage "$APPIMAGETOOL_URL" \
    && chmod +x /opt/appimagetool.AppImage \
    && printf '#!/usr/bin/env bash\nexec /opt/appimagetool.AppImage --appimage-extract-and-run "$@"\n' > /usr/local/bin/appimagetool \
    && chmod +x /usr/local/bin/appimagetool

WORKDIR /work
