#!/bin/zsh
set -euo pipefail

DIR=${0:a:h}
for file in "$DIR/.venv/bin/python" "$DIR/toupcam.py" "$DIR/libtoupcam.dylib" "$DIR/libbiohd_shim.dylib"; do
  [[ -e "$file" ]] || { echo "尚未安装，请先双击 setup.command。"; read -k 1; exit 1; }
done

export DYLD_INSERT_LIBRARIES="$DIR/libbiohd_shim.dylib"
exec "$DIR/.venv/bin/python" "$DIR/live.py" "$@"
