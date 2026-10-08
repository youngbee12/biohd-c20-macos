#!/bin/zsh
set -euo pipefail

DIR=${0:a:h}
SDK_URL=${BIOHD_SDK_URL:-https://www.touptekphotonics.com/downloads/software/toupcamsdk.20260519.zip}

command -v python3 >/dev/null || { echo "需要 Python 3。"; exit 1; }
command -v clang >/dev/null || { echo "请先安装 Xcode Command Line Tools：xcode-select --install"; exit 1; }

if [[ ! -f "$DIR/libtoupcam.dylib" || ! -f "$DIR/toupcam.py" ]]; then
  command -v curl >/dev/null || { echo "需要 curl。"; exit 1; }
  command -v unzip >/dev/null || { echo "需要 unzip。"; exit 1; }
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT
  echo "正在下载官方 ToupCam SDK（约 260 MB）…"
  curl -fL --progress-bar "$SDK_URL" -o "$TMP_DIR/toupcam-sdk.zip"
  unzip -jo "$TMP_DIR/toupcam-sdk.zip" mac/libtoupcam.dylib python/toupcam.py -d "$DIR"
fi

clang -dynamiclib "$DIR/biohd_shim.c" -o "$DIR/libbiohd_shim.dylib" \
  -framework IOKit -framework CoreFoundation -Wall -Wextra
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DIR/.venv/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"

echo "安装完成。双击 run.command 启动。"
