#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:-woow-ha-opendesign:test}
container="woow-od-smoke-${RANDOM}"
volume="woow-od-data-${RANDOM}"
port=${SMOKE_PORT:-18099}
tmp=$(mktemp -d)

cleanup() {
  local status=$?
  if (( status != 0 )); then
    echo '--- smoke container logs ---' >&2
    docker logs "$container" >&2 || true
  fi
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

docker volume create "$volume" >/dev/null

start_container() {
  docker run -d --platform linux/amd64 --name "$container" \
    -p "127.0.0.1:${port}:8099" \
    -v "$volume:/data" \
    "$image" >/dev/null
}

wait_for_health() {
  local attempt
  for ((attempt = 1; attempt <= 90; attempt += 1)); do
    if curl -fsS "http://127.0.0.1:${port}/api/health" >"$tmp/health.json"; then
      return 0
    fi
    if ! docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
      docker logs "$container" >&2 || true
      return 1
    fi
    sleep 1
  done
  docker logs "$container" >&2 || true
  echo 'health endpoint did not become ready' >&2
  return 1
}

start_container
wait_for_health
python3 - "$tmp/health.json" <<'PY'
import json
import sys
assert json.load(open(sys.argv[1], encoding='utf-8')).get('ok') is True
PY

# HA Supervisor removes the public ingress prefix before proxying and supplies
# it in X-Ingress-Path. Nginx therefore receives '/' and must inject/rewrite the
# prefix into the returned application shell.
ingress_prefix=/api/hassio_ingress/abcdefghijklmnop
curl --fail-with-body -sSL -o "$tmp/ingress.html" \
  -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/"
grep -Fq "window.__OD_INGRESS_PATH__=\"$ingress_prefix\"" "$tmp/ingress.html"
grep -Eq "(href|src)=\\\"$ingress_prefix/_next/" "$tmp/ingress.html"

# This models a browser request to <public-prefix>/api/health after Supervisor
# path stripping: nginx sees /api/health plus the validated prefix header.
curl --fail-with-body -sS -o "$tmp/ingress-health.json" \
  -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/api/health"
python3 - "$tmp/ingress-health.json" <<'PY'
import json
import sys
assert json.load(open(sys.argv[1], encoding='utf-8')).get('ok') is True
PY

docker exec "$container" sh -ceu '
  # PID 1 is root only to prepare the Supervisor root-owned /data mount.
  test "$(id -u)" = 0
  test "$(stat -c %u:%g /data/opendesign)" = 1001:1001
  for process in node nginx; do
    pids=$(pidof "$process")
    test -n "$pids"
    for pid in $pids; do
      set -- $(grep "^Uid:" "/proc/$pid/status")
      test "$2 $3 $4" = "1001 1001 1001"
    done
  done
  test -d /data/opendesign
  test -r /app/apps/daemon/dist/cli.js
  test -d /app/apps/web/out
  test -x /usr/bin/chromium-browser
  command -v bash >/dev/null
  command -v su-exec >/dev/null
  test -r /opt/ha-opendesign/headless-entry.mjs
  test -r /opt/ha-opendesign/headless-renderer.mjs
  test -r /opt/ha-opendesign/ha-export-bridge.js
  for executable in claude codex opencode aider gemini cursor-agent qwen copilot amp; do
    if command -v "$executable" >/dev/null 2>&1 \
      || test -e "/app/node_modules/.bin/$executable" \
      || test -e "/usr/local/lib/node_modules/.bin/$executable"; then
      echo "forbidden local AI CLI present: $executable" >&2
      exit 1
    fi
  done
'
docker exec -u 1001:1001 "$container" sh -ceu '
  test -w /data/opendesign
  printf persisted > /data/opendesign/container-smoke-sentinel
'

# Stop/recreate the container while retaining only its named /data volume.
docker stop -t 10 "$container" >/dev/null
docker rm "$container" >/dev/null
start_container
wait_for_health
python3 - "$tmp/health.json" <<'PY'
import json
import sys
assert json.load(open(sys.argv[1], encoding='utf-8')).get('ok') is True
PY
docker exec "$container" grep -qx persisted /data/opendesign/container-smoke-sentinel

# Direct renderer acceptance uses the Chromium and playwright-core installed in
# the image. It requires no provider key or generation call.
docker cp tests/container-renderer-e2e.mjs "$container:/tmp/container-renderer-e2e.mjs"
docker exec "$container" node /tmp/container-renderer-e2e.mjs

# Create only daemon metadata over HTTP, then seed deterministic fixture HTML in
# that project's persistent directory. No BYOK call is involved.
# As above, this is the stripped nginx-side shape of the browser's prefixed API
# request. The response proves a non-health API survives ingress forwarding.
curl --fail-with-body -sS -o "$tmp/project.json" \
  -H "X-Ingress-Path: $ingress_prefix" \
  -H 'content-type: application/json' \
  --data '{"id":"ha-smoke","name":"HA smoke","skipDiscoveryBrief":true}' \
  "http://127.0.0.1:${port}/api/projects"
python3 - "$tmp/project.json" <<'PY'
import json
import sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
assert 'ha-smoke' in json.dumps(body), body
PY
python3 - "$tmp/deck-file.json" <<'PY'
import json
import sys
html = '''<!doctype html><html><head><style>
html,body{margin:0;background:#fff}.slide{width:640px;height:360px;display:block;color:#fff;font:32px sans-serif}
.slide:first-of-type{background:#165dba}.slide:last-of-type{background:#a33}
</style></head><body><section class="slide">Slide one</section><section class="slide">Slide two</section></body></html>'''
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump({'name': 'deck.html', 'content': html}, handle)
PY
curl --fail-with-body -sS -o "$tmp/deck-file-response.json" \
  -H "X-Ingress-Path: $ingress_prefix" \
  -H 'content-type: application/json' \
  --data-binary "@$tmp/deck-file.json" \
  "http://127.0.0.1:${port}/api/projects/ha-smoke/files"
grep -Fq 'deck.html' "$tmp/deck-file-response.json"

# Run the actual injected scripts in Chromium through a Supervisor-style proxy
# that receives the public prefix, strips it, and supplies X-Ingress-Path to
# nginx. The probes exercise real browser transports and real export endpoints.
docker cp tests/container-ingress-browser-e2e.mjs "$container:/opt/ha-opendesign/container-ingress-browser-e2e.mjs"
docker exec "$container" node /opt/ha-opendesign/container-ingress-browser-e2e.mjs

# Start the real renderer acceptance in a fresh process namespace. Alpine
# crashpad state can remain unusable after closing the bridge-test Chromium on
# constrained GitHub runners even when no process is left to wait for.
docker stop -t 10 "$container" >/dev/null
docker rm "$container" >/dev/null
start_container
wait_for_health

post_export() {
  local endpoint=$1 body=$2 output=$3
  curl --fail-with-body -sS -o "$output" \
    -H 'content-type: application/json' --data "$body" \
    "http://127.0.0.1:${port}/api/projects/ha-smoke/export/${endpoint}"
  test -s "$output"
}

post_export image '{"fileName":"deck.html","deck":true,"imageFormat":"png"}' "$tmp/deck.png"
post_export image '{"fileName":"deck.html","deck":true,"imageFormat":"jpeg"}' "$tmp/deck.jpg"
post_export pdf-image '{"fileName":"deck.html","deck":true,"title":"Smoke"}' "$tmp/deck.pdf"
post_export pptx '{"fileName":"deck.html","deck":true,"title":"Smoke"}' "$tmp/deck.pptx"

docker cp "$tmp/deck.pdf" "$container:/tmp/smoke-deck.pdf" >/dev/null
test "$(docker exec "$container" pdfinfo /tmp/smoke-deck.pdf | awk '/^Pages:/ { print $2 }')" = 2

python3 - "$tmp/deck.png" "$tmp/deck.jpg" "$tmp/deck.pdf" "$tmp/deck.pptx" <<'PY'
from pathlib import Path
import io
import re
import struct
import sys
import zipfile
import zlib

png, jpg, pdf, pptx = map(Path, sys.argv[1:])


def png_pixels(data):
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    offset = 8
    compressed = bytearray()
    width = height = color_type = None
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b'IHDR':
            width, height, depth, color_type = struct.unpack('>IIBB', payload[:10])
            assert depth == 8 and color_type in (2, 6)
        elif kind == b'IDAT':
            compressed.extend(payload)
        elif kind == b'IEND':
            break
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(compressed)
    rows = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor:cursor + stride]
        cursor += stride
        row = bytearray(stride)
        for index, byte in enumerate(encoded):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                raise AssertionError(f'unsupported PNG filter {filter_type}')
            row[index] = (byte + predictor) & 0xff
        rows.append(row)
        previous = row
    return width, height, channels, rows


def jpeg_dimensions(data):
    assert data.startswith(b'\xff\xd8\xff')
    offset = 2
    while offset + 8 < len(data):
        if data[offset] != 0xff:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in (0xd8, 0xd9):
            offset += 2
            continue
        length = struct.unpack('>H', data[offset + 2:offset + 4])[0]
        if 0xc0 <= marker <= 0xc3:
            return struct.unpack('>HH', data[offset + 5:offset + 9])
        offset += 2 + length
    raise AssertionError('JPEG dimensions not found')


png_data = png.read_bytes()
width, height, channels, rows = png_pixels(png_data)
# Upstream may preserve the requested viewport around the two stacked slides,
# so assert the authored content extent and both slide colors rather than a
# tightly-cropped canvas size.
assert width >= 640 and height >= 720, (width, height)
sample_x = 320 * channels
top = tuple(rows[180][sample_x:sample_x + 3])
bottom = tuple(rows[540][sample_x:sample_x + 3])
assert all(abs(actual - expected) <= 3 for actual, expected in zip(top, (22, 93, 186))), top
assert all(abs(actual - expected) <= 3 for actual, expected in zip(bottom, (170, 51, 51))), bottom

jpg_data = jpg.read_bytes()
jpeg_height, jpeg_width = jpeg_dimensions(jpg_data)
assert jpeg_width >= 640 and jpeg_height >= 720, (jpeg_width, jpeg_height)

pdf_data = pdf.read_bytes()
assert pdf_data.startswith(b'%PDF-') and len(pdf_data) > 100

pptx_data = pptx.read_bytes()
assert pptx_data.startswith(b'PK') and len(pptx_data) > 100
with zipfile.ZipFile(io.BytesIO(pptx_data)) as archive:
    slides = [name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
assert len(slides) == 2, slides
print('HTTP exports: two-color full-deck PNG/JPEG, 2-page PDF, and 2-slide PPTX')
PY

editable_status=$(curl -sS -o "$tmp/editable.json" -w '%{http_code}' \
  -H 'content-type: application/json' \
  --data '{"fileName":"deck.html","deck":true,"editable":true}' \
  "http://127.0.0.1:${port}/api/projects/ha-smoke/export/pptx")
test "$editable_status" = 502
grep -qi 'Editable PPTX is unsupported' "$tmp/editable.json"

# The seeded project and DB record remain after the earlier restart; this export
# set proves renderer/assembly operation without needing an AI provider key.
echo 'container smoke: real-browser HA prefix/probes/actions, health/API, persistence, renderer, and HTTP assembly passed'
