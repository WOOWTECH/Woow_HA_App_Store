#!/usr/bin/env bash
# Verify the two providers this add-on ships with actually respond.
#
# Reads keys from the environment (same names used inside the add-on):
#   GLM_API_KEY       — required
#   MINIMAX_API_KEY   — optional; skipped if unset
#
# Exits non-zero if any required provider fails, so it plugs into CI.
set -uo pipefail

PASS=0; FAIL=0; SKIP=0

pass() { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m  %s\n         %s\n' "$1" "$2"; }
skip() { SKIP=$((SKIP+1)); printf '  \033[33mSKIP\033[0m  %s\n         %s\n' "$1" "$2"; }

need() { command -v "$1" >/dev/null || { echo "missing: $1"; exit 2; }; }
need curl
need jq

probe() {
  local name="$1" url="$2" key="$3" model="$4" expect_substr="$5"
  local body http out content
  body=$(printf '{"model":"%s","messages":[{"role":"user","content":"reply OK"}],"max_tokens":32,"temperature":0}' "$model")
  out=$(mktemp)
  http=$(curl -sS -o "$out" -w '%{http_code}' \
    -X POST "$url" \
    -H "Authorization: Bearer ${key}" \
    -H 'Content-Type: application/json' \
    -d "$body")
  if [ "$http" != "200" ]; then
    fail "$name" "HTTP $http: $(head -c 200 "$out")"
    rm -f "$out"; return 1
  fi
  content=$(jq -r '.choices[0].message.content // ""' < "$out" 2>/dev/null)
  if [ -z "$content" ]; then
    fail "$name" "200 but empty content: $(head -c 200 "$out")"
    rm -f "$out"; return 1
  fi
  if [ -n "$expect_substr" ] && ! printf '%s' "$content" | grep -q "$expect_substr"; then
    fail "$name" "content missing expected marker '$expect_substr': $(printf '%s' "$content" | head -c 200)"
    rm -f "$out"; return 1
  fi
  pass "$name — 200, $(printf '%s' "$content" | wc -c | tr -d ' ') chars back"
  rm -f "$out"
}

echo "── GLM-4.6 (thinkingFormat: zai) ──"
if [ -z "${GLM_API_KEY:-}" ]; then
  fail "GLM-4.6" "GLM_API_KEY not set"
else
  probe "GLM-4.6" \
    "https://open.bigmodel.cn/api/paas/v4/chat/completions" \
    "$GLM_API_KEY" "glm-4.6" ""
fi

echo "── MiniMax-M3 (thinkingFormat: deepseek — expect <think> in content) ──"
if [ -z "${MINIMAX_API_KEY:-}" ]; then
  skip "MiniMax-M3" "MINIMAX_API_KEY not set (optional)"
else
  probe "MiniMax-M3" \
    "https://api.minimax.io/v1/chat/completions" \
    "$MINIMAX_API_KEY" "MiniMax-M3" "<think>"
fi

echo
echo "── Summary: ${PASS} pass / ${FAIL} fail / ${SKIP} skip ──"
[ "$FAIL" -eq 0 ]
