#!/usr/bin/env bash
set -euo pipefail
task_harness_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export QA_ROOT="${QA_ROOT:-$(dirname -- "$task_harness_dir")}"
export PYTHONDONTWRITEBYTECODE=1
if [[ -n "${QA_CHECK_OUTPUT:-}" ]]; then
  # mkdir (without -p) rejects an existing destination, including symlinks.
  mkdir -m 700 -- "$QA_CHECK_OUTPUT"
  task_run_dir=$(cd -- "$QA_CHECK_OUTPUT" && pwd)
else
  if [[ -z "${QA_OUTPUT:-}" ]]; then
    [[ ! -L "$QA_ROOT/evidence" ]] || { echo 'evidence must not be a symlink' >&2; exit 1; }
    mkdir -p -- "$QA_ROOT/evidence"
  fi
  task_run_dir=$(mktemp -d "${QA_OUTPUT:-$QA_ROOT/evidence}/project-lab-check-XXXXXXXX")
fi
export QA_OUTPUT="$task_run_dir"
export QA_PACKAGES="${QA_PACKAGES:-$QA_ROOT}"
node "$task_harness_dir/source-contract.mjs"
python3 -B -m unittest discover -s "$task_harness_dir/tests" -p 'test_*.py'
node "$task_harness_dir/test-all.mjs"
node "$task_harness_dir/runtime-tests.mjs"
if [[ "$QA_PACKAGES" == "$QA_ROOT" ]]; then
  python3 -B "$task_harness_dir/package.py" --root "$QA_ROOT"
else
  python3 -B "$task_harness_dir/package.py" --root "$QA_ROOT" --output "$QA_PACKAGES"
fi
node "$task_harness_dir/standalone.mjs"
node "$task_harness_dir/optimization-audit.mjs"
node -e 'console.log(JSON.stringify({ok:true,output:process.env.QA_OUTPUT,packages:process.env.QA_PACKAGES}))'
