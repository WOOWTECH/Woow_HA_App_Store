#!/usr/bin/env python3
"""Add a durable pause contract to the canonical PaaS host supervisor.

Apply to a build/staging copy or canonical chart source, then vendor through
the chart's normal sync process. Do not mutate a live read-only ConfigMap.
"""
import argparse
import hashlib
from pathlib import Path

SOURCE_HASH = "88e3718688edc48cee39d4c323520eb5c0165e6796e683fee3e267676015870c"
MARKER = "WOOW_CONNECTOR_PAUSE_V1"


def transform(source):
    def once(anchor, replacement):
        nonlocal source
        if source.count(anchor) != 1:
            raise ValueError("Supervisor pause patch anchor changed")
        source = source.replace(anchor, replacement, 1)
    once('TOKENS=$OG_DATA_DIR/auth_tokens.json\n',
         '# WOOW_CONNECTOR_PAUSE_V1: one persistent control file, existing manager owns all signals.\n'
         'OG_PAUSE_FILE=${OG_PAUSE_FILE:-$OG_STATE_DIR/connector-paused}\n'
         'TOKENS=$OG_DATA_DIR/auth_tokens.json\n')
    once('  while :; do\n    if [ ! -s "$TOKENS" ]; then\n',
         '  while :; do\n'
         '    if [ -e "$OG_PAUSE_FILE" ]; then\n'
         '      ST_RETRY_AT=""\n'
         '      set_status paused "paused by code-server connector" "Resume in WOOW Omnigent"\n'
         '      nap "$OG_TICK_SECONDS"\n'
         '      _last_fp="unset"\n'
         '      continue\n'
         '    fi\n'
         '    if [ ! -s "$TOKENS" ]; then\n')
    once('    kill -0 "$child" 2>/dev/null || break\n    _t=$(now)\n',
         '    kill -0 "$child" 2>/dev/null || break\n'
         '    if [ -e "$OG_PAUSE_FILE" ]; then\n'
         '      STOP_REASON=paused\n'
         '      stop_host\n'
         '      set_status paused "paused by code-server connector" "Resume in WOOW Omnigent"\n'
         '      return 0\n'
         '    fi\n'
         '    _t=$(now)\n')
    once('  while [ "$(now)" -lt "$_end" ]; do\n',
         '  while [ "$(now)" -lt "$_end" ]; do\n'
         '    [ -e "$OG_PAUSE_FILE" ] && break\n')
    once('  wait_for_login\n  start_host\n',
         '  wait_for_login\n  [ -e "$OG_PAUSE_FILE" ] && continue\n  start_host\n')
    once('  watch_host\n  EXIT_FP=$(fingerprint)\n',
         '  watch_host\n  [ "$STOP_REASON" = paused ] && continue\n  EXIT_FP=$(fingerprint)\n')
    return source


def patch(file):
    file = Path(file)
    source = file.read_text()
    if MARKER in source:
        # Idempotence has an integrity receipt; a marker alone is not enough.
        receipt = file.with_name(file.name + ".woow-pause.sha256")
        if not receipt.exists() or receipt.read_text().strip() != hashlib.sha256(source.encode()).hexdigest():
            raise ValueError("Supervisor pause patch receipt mismatch")
        return
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_HASH:
        raise ValueError("Supervisor source changed; review/update patch before deployment")
    result = transform(source)
    file.write_text(result)
    file.with_name(file.name + ".woow-pause.sha256").write_text(hashlib.sha256(result.encode()).hexdigest() + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("supervisor")
    args = parser.parse_args()
    patch(args.supervisor)
    print("WOOW_CONNECTOR_PAUSE_V1 applied")
