#!/usr/bin/env python3
"""Reproduce this source-only review. Writes proof and fixtures only in HERE.

For actual image validation, use INTEGRATION.md's strict check-only + explicit
PI_NATIVE_MAINTENANCE_TEST_SOURCE commands under the image interpreter.
"""
from __future__ import annotations
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
PROOF = HERE / "proof"
TMP = HERE / "tmp"
TMP.mkdir(mode=0o700, exist_ok=True)
PROOF.mkdir(exist_ok=True)
os.environ["TMPDIR"] = str(TMP)
tempfile.tempdir = str(TMP)
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE / "tests"))
from test_maintenance_preservation import CAPTURED, age_predicate, load_common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, args, *, cwd=HERE, source=None, expect=0):
    env = dict(os.environ, TMPDIR=str(TMP), PYTHONDONTWRITEBYTECODE="1")
    env.pop("PI_NATIVE_MAINTENANCE_TEST_SOURCE", None)
    if source is not None:
        env["PI_NATIVE_MAINTENANCE_TEST_SOURCE"] = str(source)
    result = subprocess.run([sys.executable, "-B", *args], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
    log = PROOF / (name + ".log")
    log.write_text(result.stdout)
    if (expect == 0 and result.returncode != 0) or (expect != 0 and result.returncode == 0):
        raise RuntimeError(name + " had unexpected status; see " + str(log))
    match = re.search(r"Ran (\d+) tests?", result.stdout)
    return {"exitCode":result.returncode,"testsRun":int(match.group(1)) if match else None,
            "log":str(log.relative_to(HERE)),"logSha256":sha(log),
            "skips": int(re.search(r"skipped=(\d+)", result.stdout).group(1)) if "skipped=" in result.stdout else 0}


def baseline_observation():
    # Exact old function on owned fixtures only; intentionally demonstrates loss.
    old = load_common(CAPTURED / "native/native_bridge_common.py")
    result = []
    for name in ("codex-home/sessions/2026/10/01/rollout-old.jsonl", "dead_letter.jsonl.1"):
        with tempfile.TemporaryDirectory(prefix="baseline-", dir=TMP) as temp:
            root = Path(temp) / "codex-native"
            bridge = root / ("b"*32)
            path = bridge / name
            path.parent.mkdir(parents=True)
            path.write_bytes(b"owned baseline fixture\n")
            owner = bridge / "owner.pid"
            owner.write_text("0")
            epoch = time.time()-8*24*60*60
            for item in (owner,path): os.utime(item,(epoch,epoch))
            eligible = age_predicate(old)(bridge)
            cleaned = old.prune_orphaned_dirs(root, should_prune=age_predicate(old))
            result.append({"fixture":name,"oldAgeEligible":eligible,"oldCleanedCount":cleaned,
                           "oldDeletedBytes":not path.exists()})
    if not all(x["oldAgeEligible"] and x["oldCleanedCount"]==1 and x["oldDeletedBytes"] for x in result):
        raise RuntimeError("original regression did not reproduce on fixtures")
    return result


def main():
    lock = json.loads((HERE / "source-lock.json").read_text())
    target = lock["files"][0]["target"]
    expected = lock["files"][0]["afterSha256"]
    if sha(HERE / "overlay" / target) != expected:
        raise RuntimeError("candidate bytes drifted")
    compiled=[]
    for rel in ["apply_maintenance_patch.py", "verify_source_patch.py", "overlay/"+target,
                "tests/test_build_patch.py", "tests/test_maintenance_preservation.py"]:
        compile((HERE/rel).read_bytes(),rel,"exec")
        compiled.append(rel)
    baseline=baseline_observation()
    overlay=run("unittest-overlay",["-m","unittest","discover","-s","tests","-v"])
    with tempfile.TemporaryDirectory(prefix="installed-proof-",dir=TMP) as temporary:
        temp=Path(temporary)
        sp=temp/"site-packages"
        installed=sp/target
        installed.parent.mkdir(parents=True)
        installed.write_bytes((CAPTURED/"native/native_bridge_common.py").read_bytes())
        cli_apply=run("fixture-installer-cli",["apply_maintenance_patch.py","--site-packages",str(sp),"--strict"])
        cli_check=run("fixture-installed-check-only",["apply_maintenance_patch.py","--site-packages",str(sp),"--strict","--check-only"])
        if sha(installed) != expected: raise RuntimeError("fixture-installed source mismatch")
        installed_suite=run("unittest-fixture-installed",["-m","unittest","discover","-s","tests","-v"],source=installed)
        # The exact requested envvar must fail collection for a wrong source.
        wrong=temp/"wrong-common.py"
        wrong.write_bytes(installed.read_bytes()+b"\n# unreviewed fixture substitution\n")
        negative=run("installed-override-negative",["tests/test_maintenance_preservation.py"],source=wrong,expect=1)
        if "exact afterSha256" not in (HERE/negative["log"]).read_text():
            raise RuntimeError("wrong installed source failed for an unexpected reason")
        # Portable package with no parent capture and no writable package fixture
        # directory. Proof checks tree bytes/names before/after; only TMPDIR is used.
        package=temp/"portable-package"
        package.mkdir()
        for rel in ("apply_maintenance_patch.py","source-lock.json"):
            shutil.copyfile(HERE/rel,package/rel)
        for rel in ("tests","fixtures","overlay"):
            shutil.copytree(HERE/rel,package/rel)
        tree_before={str(q.relative_to(package)):sha(q) for q in package.rglob("*") if q.is_file()}
        portable=run("unittest-portable-installed",["-m","unittest","discover","-s","tests","-v"],cwd=package,source=installed)
        tree_after={str(q.relative_to(package)):sha(q) for q in package.rglob("*") if q.is_file()}
        if tree_before != tree_after: raise RuntimeError("portable tests wrote into package")
    before=json.loads((PROOF/"original-43-before.json").read_text())
    after={rel:{"sha256":sha(HERE.parent/rel),"bytes":(HERE.parent/rel).stat().st_size} for rel in before}
    if before != after or len(after)!=43: raise RuntimeError("original capture drift")
    (PROOF/"original-43-after.json").write_text(json.dumps(after,indent=2)+"\n")
    event=HERE.parent.parent/"root-pi3-migration-hold-20261122T0001/persistent-maintenance-events.json"
    if sha(event)!="15cf3deb88cda84c42cbcd14555e986479c757c472e089c58fd54bda41bdee9e":
        raise RuntimeError("root event receipt changed")
    result={"schema":"native-maintenance-source-verification-v1",
        "status":"SOURCE_TESTS_PASS_NO_PRODUCTION_ACCEPTANCE",
        "utc":datetime.now(timezone.utc).isoformat(),
        "python":platform.python_version(),"platform":platform.system(),
        "filelock":importlib.metadata.version("filelock"),
        "candidateSha256":expected,"lockSha256":sha(HERE/"source-lock.json"),
        "baselineOwnedFixtures":baseline,"overlaySuite":overlay,
        "fixtureInstallerCli":cli_apply,"fixtureInstalledCheckOnly":cli_check,
        "fixtureInstalledSourceSuite":installed_suite,"installedSourceOverrideNegative":negative,
        "portableInstalledSourceSuite":portable,"portablePackageBytesAndPathsUnchanged":True,
        "syntaxChecked":compiled,"originalCapturedSourcesUnchanged":len(after),
        "rootEventReceiptSha256":sha(event),
        "eventInterpretation":"strong count/timing correlation; no per-directory identity proof",
        "scope":{"overlayFiles":1,"liveSdkImports":0,"providerRuns":0,"productionCalls":0,
                 "imageBuilds":0,"liveUserDataReads":0,"archiveCopies":0,"restoredLostHistories":0},
        "limits":["owned source fixtures, not actual image/production execution",
                  "actual image Python 3.12 source binding remains root-owned",
                  "cooperative preparation lock; arbitrary writers after final check not excluded",
                  "config/auth and all nonmarker leaves retained; reduced automatic reclamation",
                  "maintenance never touches attachment caches",
                  "explicit session/resource DELETE remains destructive and unchanged",
                  "Pi3 migration HOLD; Pi4 NO APPLY; Pi1 paused"]}
    (PROOF/"source-verification.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"candidateSha256":expected,
        "overlayTests":overlay["testsRun"],"fixtureInstalledTests":installed_suite["testsRun"],
        "portableTests":portable["testsRun"],"portableSkips":portable["skips"],
        "originalSourcesUnchanged":len(after),"proof":"proof/source-verification.json"},indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
