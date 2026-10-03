#!/usr/bin/env bash
# Einrichtung auf der Linux-VM: venv + Python-Pakete. ffmpeg muss installiert sein.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "ffmpeg/ffprobe fehlen -> sudo apt install -y ffmpeg" >&2
  exit 1
fi
if ! ffmpeg -hide_banner -protocols 2>/dev/null | grep -qx '  srt'; then
  echo "Hinweis: dieses ffmpeg kann kein SRT – dann RTSP von MediaMTX nutzen." >&2
fi

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo
echo "Fertig. Start z. B.:"
echo "  .venv/bin/python -m tafeluhr --source 'srt://MEDIAMTX:8890?streamid=read:PFAD' --record aufnahmen --log lesungen.csv"
echo "Dann im Browser: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8090/"
