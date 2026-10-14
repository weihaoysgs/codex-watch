#!/bin/sh
set -eu
# This script is for the disposable test container, not the user's desktop.
test "${CODEX_WATCH_IME_TEST:-}" = 1
export DISPLAY=:99
Xvfb "$DISPLAY" -screen 0 1280x900x24 -ac >/tmp/codex-watch-xvfb.log 2>&1 &
sleep 1
if [ "${QT_IM_MODULE:-}" = ibus ]; then
    ibus-daemon --daemonize --replace --xim --panel disable >/tmp/codex-watch-ime.log 2>&1
else
    fcitx -d >/tmp/codex-watch-ime.log 2>&1
fi
sleep 2
python3 /work/tests/live_input_method.py
