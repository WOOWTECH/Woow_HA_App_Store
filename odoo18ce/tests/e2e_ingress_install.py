#!/usr/bin/env python3
"""Install Odoo modules through the Ingress Apps screen, one at a time.

Issue #144's parity run installs 29 modules on a fresh database through the
Ingress surface, never the Public origin or the command line: the install
itself is part of what is tested. For each module in dependency order the
driver opens the module's form in the Apps screen under the Ingress prefix,
presses Activate, waits until Odoo reports the module installed, then reads
the next Rewrite scan round from the add-on log and the Rewrite scan
notifications Home Assistant holds (handoff #10).

The first round logged after the install may have started before the install
finished; the driver does not tell the two apart.

The pure parts are tested in the static tier by test_e2e_ingress_install.py.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Iterable, Mapping, NamedTuple, Sequence

from e2e_menu_action_adapter import SurfaceDriver, parse_env_file
from e2e_menu_action_crawler import Surface

# The Rewrite scan's own vocabulary, read from its source rather than copied.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rootfs/usr/local/lib"))
import rewrite_apply  # noqa: E402

# `rewrite_apply.report` opens each round with this line and names the
# prefixes it generated on an indented `prefixes:` line.
_ROUND = re.compile(r"Rewrite scan \(apply\): (.+?)\s*$")
_PREFIXES = re.compile(r"^\S*\s+prefixes: (.+?)\s*$")

#: Every id the Rewrite scan notifies under starts with the added-rules id.
REWRITE_NOTIFICATION_PREFIX = os.path.commonprefix(list(rewrite_apply.NOTIFICATION_IDS.values()))
#: Handoff #10: a round within five minutes of the install.
SCAN_ROUND_LIMIT_SECONDS = 300
INSTALL_TIMEOUT_SECONDS = 1200
#: Polling stops a little after the limit, so a late round is recorded as late.
SCAN_WAIT_SECONDS = SCAN_ROUND_LIMIT_SECONDS + 120
POLL_SECONDS = 15
PAGE_TIMEOUT_MS = 120000
BUTTON_TIMEOUT_MS = 60000
UPDATE_LIST_TIMEOUT_MS = 300000


class ScanRound(NamedTuple):
    status: str
    prefixes: tuple[str, ...]


def scan_rounds(lines: Iterable[str]) -> list[ScanRound]:
    """The Rewrite scan rounds an add-on log excerpt reports, in order."""
    rounds: list[ScanRound] = []
    for line in lines:
        start = _ROUND.search(line)
        if start:
            rounds.append(ScanRound(start.group(1), ()))
            continue
        more = _PREFIXES.search(line)
        if more and rounds:
            rounds[-1] = rounds[-1]._replace(prefixes=tuple(more.group(1).split()))
    return rounds


def new_rewrite_notifications(
    before: Iterable[Mapping[str, str]], after: Iterable[Mapping[str, str]],
) -> list[Mapping[str, str]]:
    """Rewrite scan notifications in `after` that `before` did not hold.

    A failure notification keeps its id round after round, so one that was
    created again counts too: its `created_at` changed.
    """
    seen = {(n["notification_id"], n.get("created_at")) for n in before}
    return [
        n for n in after
        if n["notification_id"].startswith(REWRITE_NOTIFICATION_PREFIX)
        and (n["notification_id"], n.get("created_at")) not in seen
    ]


def judge_install(
    state: str, rounds: Sequence[ScanRound], notifications: Sequence[Mapping[str, str]],
    round_seconds: int | None,
) -> list[str]:
    """What an install broke of #144's promise; empty when it kept all of it."""
    problems = []
    if state != "installed":
        problems.append("module is %s, not installed" % state)
    if not rounds:
        problems.append("no Rewrite scan round was logged")
        return problems
    if round_seconds is not None and round_seconds > SCAN_ROUND_LIMIT_SECONDS:
        problems.append("the first round came after %d s, not within %d s"
                        % (round_seconds, SCAN_ROUND_LIMIT_SECONDS))
    first = rounds[0]
    if first.status not in rewrite_apply.HEALTHY_STATUSES:
        problems.append("the round ended '%s'" % first.status)
    if first.prefixes and not notifications:
        problems.append("rules were added (%s) but no notification appeared" % " ".join(first.prefixes))
    return problems


def install_order(targets: Sequence[str], deps: Mapping[str, Iterable[str]]) -> list[str]:
    """The targets ordered so each comes after every target it depends on.

    `deps` holds each module's direct dependencies, targets or not; a
    dependency outside the targets is walked through but left to Odoo to
    install. Ties go alphabetically, so a run is repeatable.
    """
    wanted = set(targets)

    def reachable(module: str) -> set[str]:
        seen: set[str] = set()
        stack = list(deps.get(module, ()))
        while stack:
            name = stack.pop()
            if name not in seen:
                seen.add(name)
                stack.extend(deps.get(name, ()))
        return seen

    before = {module: reachable(module) & wanted for module in wanted}
    order: list[str] = []
    while len(order) < len(wanted):
        ready = sorted(m for m in wanted - set(order) if before[m] <= set(order))
        if not ready:
            raise ValueError("dependency cycle among %s" % sorted(wanted - set(order)))
        order.append(ready[0])
    return order


# --- Live driver ------------------------------------------------------------


class IngressApps:
    """The Apps screen under the Ingress prefix, driven like an operator would."""

    def __init__(self, driver: SurfaceDriver) -> None:
        self.driver = driver
        self.page = driver.context.new_page()

    def rpc(self, model: str, method: str, args: list, kwargs: Mapping | None = None):
        response = self.driver.context.request.post(
            self.driver.base + "/web/dataset/call_kw/%s/%s" % (model, method),
            data={"jsonrpc": "2.0", "method": "call", "params": {
                "model": model, "method": method, "args": args, "kwargs": dict(kwargs or {}),
            }},
        )
        body = response.json()
        if response.status != 200 or "error" in body:
            raise RuntimeError("%s.%s failed: %s" % (model, method, body.get("error", {}).get("message")))
        return body.get("result")  # absent when the method returns None

    def modules(self, names: Sequence[str]) -> dict[str, dict]:
        rows = self.rpc("ir.module.module", "search_read", [[["name", "in", list(names)]]],
                        {"fields": ["name", "state"]})
        return {row["name"]: row for row in rows}

    def dependencies(self) -> dict[str, set[str]]:
        rows = self.rpc("ir.module.module.dependency", "search_read", [[]],
                        {"fields": ["module_id", "name"]})
        deps: dict[str, set[str]] = {}
        ids = {row["module_id"][0] for row in rows}
        names = {row["id"]: row["name"] for row in self.rpc(
            "ir.module.module", "search_read", [[["id", "in", sorted(ids)]]], {"fields": ["name"]})}
        for row in rows:
            deps.setdefault(names[row["module_id"][0]], set()).add(row["name"])
        return deps

    def update_list(self) -> None:
        """Apps > Update Apps List, so modules copied into the addons path show up."""
        self.page.goto(self.driver.base + "/odoo/action-base.action_view_base_module_update",
                       wait_until="load", timeout=PAGE_TIMEOUT_MS)
        self.page.locator('button[name="update_module"]').click()
        self.page.locator(".modal").wait_for(state="detached", timeout=UPDATE_LIST_TIMEOUT_MS)

    def install(self, module_id: int) -> None:
        self.page.goto(self.driver.base + "/odoo/action-base.open_module_tree/%d" % module_id,
                       wait_until="load", timeout=PAGE_TIMEOUT_MS)
        button = self.page.locator('button[name="button_immediate_install"]')
        button.wait_for(timeout=BUTTON_TIMEOUT_MS)
        button.click()


def _log_since(command: str, since: int) -> list[str]:
    done = subprocess.run(shlex.split(command.format(since=since)), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    return (done.stdout + done.stderr).splitlines()


def _wait_for(check, limit_seconds: int, driver: SurfaceDriver):
    """Poll `check` until it returns something truthy or the limit passes."""
    started = time.time()
    value = None
    while time.time() - started < limit_seconds:
        time.sleep(POLL_SECONDS)
        driver.ingress.keep_alive()
        try:
            value = check()
        except Exception:  # noqa: BLE001 -- the registry reloads during an install
            continue
        if value:
            break
    return value


def run_installs(modules: Sequence[str], log_command: str, out, *, update_list: bool) -> int:
    from playwright.sync_api import sync_playwright

    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        driver = SurfaceDriver(Surface.HA_INGRESS, browser,
                               ignore_https_errors=os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1")
        try:
            driver.log_in()
            apps = IngressApps(driver)
            if update_list:
                apps.update_list()
            known = apps.modules(modules)
            missing = sorted(set(modules) - set(known))
            if missing:
                raise RuntimeError("not in the Apps list: %s" % ", ".join(missing))
            for module in install_order(modules, apps.dependencies()):
                record = {"module": module, "database": os.environ.get("ODOO_DB", "default")}
                if apps.modules([module])[module]["state"] == "installed":
                    record.update(result="already installed")
                    out.write(json.dumps(record) + "\n")
                    out.flush()
                    continue
                before = driver.ingress.notifications()
                started = time.time()
                apps.install(known[module]["id"])
                installed = _wait_for(
                    lambda: apps.modules([module])[module]["state"] == "installed",
                    INSTALL_TIMEOUT_SECONDS, driver)
                state = "installed" if installed else apps.modules([module])[module]["state"]
                done_at = int(time.time())
                rounds = _wait_for(lambda: scan_rounds(_log_since(log_command, done_at)),
                                   SCAN_WAIT_SECONDS, driver) if installed else []
                round_seconds = int(time.time()) - done_at if rounds else None
                added = new_rewrite_notifications(before, driver.ingress.notifications())
                problems = judge_install(state, rounds or [], added, round_seconds)
                record.update(
                    state=state, install_seconds=done_at - int(started),
                    scan_rounds=[r._asdict() for r in rounds or []],
                    scan_round_seconds=round_seconds,
                    notifications=[{"id": n["notification_id"], "title": n.get("title")} for n in added],
                    problems=problems,
                )
                failures += bool(problems)
                out.write(json.dumps(driver.masker.value(record), ensure_ascii=False) + "\n")
                out.flush()
                print("%s %s %s" % ("FAIL" if problems else "OK  ", module, "; ".join(problems) or state),
                      file=sys.stderr)
                if not installed:
                    break  # a later module may depend on this one
        finally:
            driver.close()
            browser.close()
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--modules", required=True, help="comma-separated module names")
    parser.add_argument("--log-command", required=True,
                        help="prints the add-on log since {since} (a Unix time), e.g. "
                             "'ssh root@<test-host> docker logs --since {since} <container>'")
    parser.add_argument("--update-list", action="store_true", help="run Update Apps List first")
    parser.add_argument("--out", required=True, help="JSONL file, one record per module")
    parser.add_argument("--env-file", help="read unset credentials from this NAME=value file")
    args = parser.parse_args(argv)
    if args.env_file:
        with open(args.env_file, encoding="utf-8") as env_file:
            parse_env_file(env_file, os.environ)
    modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    with open(args.out, "a", encoding="utf-8") as out:
        return run_installs(modules, args.log_command, out, update_list=args.update_list)


if __name__ == "__main__":
    sys.exit(main())
