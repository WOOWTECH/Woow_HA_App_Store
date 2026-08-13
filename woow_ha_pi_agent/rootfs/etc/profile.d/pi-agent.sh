# Video pipeline env — sourced by interactive shells (addon "Terminal" tab,
# `docker exec -it ... bash`, etc.). The pi-web longrun sets the same three
# variables directly so subprocesses spawned by the pi coding agent inherit
# them without needing a login shell.
if [ -x /data/pi-agent/venv/bin/python3 ]; then
    export PATH="/data/pi-agent/venv/bin:${PATH}"
fi
export PLAYWRIGHT_BROWSERS_PATH=/data/pi-agent/playwright-cache
export RCLONE_CONFIG=/data/pi-agent/rclone/rclone.conf
