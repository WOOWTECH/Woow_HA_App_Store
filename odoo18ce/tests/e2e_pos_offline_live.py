#!/usr/bin/env python3
"""POS offline on both surfaces (#161, ADR 0011, parity plan U-C27).

    python odoo18ce/tests/e2e_pos_offline_live.py run --env-file .env --db odoo_parity \
        --out checks.jsonl [--run-id WOOW-PARITY-...] [--config "Furniture Shop"]

On each surface -- the Public origin, then the add-on panel in Home Assistant
with Odoo in its Ingress iframe -- the run opens `/pos/ui` of the config's
open session, cuts the network with the browser's offline emulation (never
the host's), sells one product for cash, restores the network and looks for
the order on the server. Then it cuts the network again and reloads
`/pos/ui`. Each surface's results go into two `odoo-parity-evidence/v1`
records, `POS offline sale` and `POS offline reload`, under U-C27.

The config needs an open session (the run does not open one), and every run
leaves one paid order per surface in it. Signals are counted while the
browser is online; what failed while it was offline is expected and goes
into the details.

The shared-layer run (#143) uses the till helpers here for U-F5 (receipt
print) and U-C25 (camera scan); unlike this run, they open a session through
the till's Opening Control when the config has none.

Environment and surfaces as in e2e_parity_shared_layers_live.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Mapping, Sequence

from e2e_menu_action_adapter import RunInfo, new_run_id, parse_env_file
from e2e_parity_shared_layers import Outcome, check_record
from e2e_parity_shared_layers_live import Env, Side, artifact_dir, open_sides

TIMEOUT = 60_000
ROUTE = "/pos/ui"
PRODUCT = "Desk Pad"
SYNC_WAIT_S = 90


# --- Pure parts (static tier: test_e2e_pos_offline.py) -------------------------


def sale_outcome(facts: Mapping[str, Any], server_rows: Sequence[Mapping[str, Any]], *, session_id: int) -> Outcome:
    """What became of the sale the till made offline, judged from the server."""
    details: dict[str, Any] = {key: facts.get(key) for key in
                               ("went_offline", "validated_offline", "offline_notice", "synced_after_s")}
    if not facts.get("went_offline"):
        return Outcome(False, "the till was never offline", details=details)
    if not facts.get("validated_offline"):
        return Outcome(True, "till could not validate the sale offline", details=details)
    order = next((row for row in server_rows if row.get("uuid") == facts.get("uuid")), None)
    if order is None:
        return Outcome(True, "offline sale not on the server after reconnect", details=details)
    details["server_order"] = {key: order.get(key) for key in
                               ("id", "pos_reference", "state", "amount_total", "session_id")}
    if (order.get("session_id") or [None])[0] != session_id:
        return Outcome(True, "offline sale landed in another session", details=details)
    return Outcome(True, "offline sale reached the server after reconnect", details=details)


_NET_ERROR = re.compile(r"net::ERR_[A-Z_]+")


def net_error(message: str) -> str | None:
    match = _NET_ERROR.search(message or "")
    return match.group(0) if match else None


def reload_outcome(error: str | None, *, till_loaded: bool) -> Outcome:
    """Whether `/pos/ui` comes back when it is loaded again with the network cut."""
    if error:
        code = net_error(error) or "error"
        return Outcome(True, "offline reload fails (%s)" % code, details={"error": code})
    return Outcome(True, "offline reload loads the till" if till_loaded else "offline reload shows no till")


def receipt_print_outcome(state: Mapping[str, Any]) -> Outcome:
    """What Print Full Receipt did (#143, U-F5): POS 18 CE without a printer calls window.print()."""
    images = state.get("images") or []
    broken = [image["src"] for image in images if not image.get("loaded")]
    details = {"print_calls": state.get("print_calls", 0), "receipt_chars": state.get("receipt_chars", 0),
               "images": len(images), "broken_images": broken}
    if not state.get("receipt_shown"):
        return Outcome(False, "the sale never reached the receipt screen", details=details)
    if not state.get("print_calls"):
        return Outcome(True, "print() never called", details=details)
    if not state.get("has_order_name"):
        return Outcome(True, "print() called without the order's receipt", details=details)
    if broken:
        return Outcome(True, "receipt printed; %d of %d images did not load" % (len(broken), len(images)),
                       details=details)
    return Outcome(True, "receipt printed", details=details)


def pos_records(run: RunInfo, public_sale: Outcome, ingress_sale: Outcome,
                public_reload: Outcome, ingress_reload: Outcome) -> list[dict[str, Any]]:
    common = {"module": "point_of_sale", "route": ROUTE}
    return [
        check_record(run, "U-C27", screen="POS offline sale", public=public_sale, ingress=ingress_sale,
                     notes="Sold offline with the browser's offline emulation, then reconnected; the order "
                           "is looked up on the server by its uuid.", **common),
        check_record(run, "U-C27", screen="POS offline reload", public=public_reload, ingress=ingress_reload,
                     notes="/pos/ui loaded again with the network cut. Odoo 18 CE's POS has no service worker "
                           "of its own.", **common),
    ]


# --- Live part ---------------------------------------------------------------

# The POS store: `posmodel` in POS 18, or through the OWL env.
_ORDER_UUID = """() => {
  const pos = window.posmodel || (odoo.__WOWL_DEBUG__ && odoo.__WOWL_DEBUG__.root.env.services.pos);
  const order = pos.getOrder ? pos.getOrder() : pos.get_order();
  return order.uuid;
}"""
_OFFLINE_NOTICE = re.compile(r"Connection Lost[^\n]*|offline[^\n]{0,80}", re.I)


def enter_till(side: Side) -> None:
    """Past the opening control and the pos_hr lock screen, to the product grid."""
    root = side.root
    products = root.locator("article.product").first
    deadline = time.time() + TIMEOUT / 1000
    while time.time() < deadline:
        # The Opening Control dialog's button first: its label is also the screen's.
        # The grid already shows behind that dialog, so it counts only without one.
        for button in (root.locator(".modal button", has_text="Open Register"),
                       root.get_by_text("Open Register"), root.get_by_text("Unlock Register")):
            if button.first.is_visible():
                button.first.click()
                break
        else:
            if products.is_visible():
                return
        side.page.wait_for_timeout(1000)
    raise RuntimeError("POS never showed its product grid")


def offline_notice(side: Side, wait_s: int = 15) -> str | None:
    for _ in range(wait_s):
        text = side.root.evaluate("() => document.body.innerText")
        match = _OFFLINE_NOTICE.search(text)
        if match:
            return match.group(0).strip()[:120]
        side.page.wait_for_timeout(1000)
    return None


def sell_one(side: Side) -> bool:
    """Product, Payment, Cash, Validate; True when the receipt screen shows."""
    root = side.root
    root.locator("article.product", has_text=PRODUCT).first.click()
    root.locator(".pay-order-button").first.click()
    root.locator(".paymentmethod", has_text="Cash").first.click()
    root.locator(".validation-button.next:not(.disabled)").first.click()
    try:
        root.get_by_text("New Order").first.wait_for(timeout=30_000)
        return True
    except Exception:  # noqa: BLE001 -- the result says it
        return False


def sum_signals(*blocks: Mapping[str, int]) -> dict[str, int]:
    total: dict[str, int] = {}
    for block in blocks:
        for name, count in block.items():
            total[name] = total.get(name, 0) + count
    return total


def offline_sale(side: Side, server: Side, session_id: int, config_id: int) -> tuple[Outcome, Outcome]:
    recorder = side.recorder
    till = "%s?config_id=%d" % (ROUTE, config_id)
    side.close_chat_windows()
    start = recorder.mark()
    side.goto(till, wait="domcontentloaded")
    enter_till(side)
    side.settle()
    online_before = recorder.since(start)
    online_details = recorder.details(start)

    facts: dict[str, Any] = {"went_offline": False, "validated_offline": False}
    offline_mark = recorder.mark()
    side.context.set_offline(True)
    try:
        facts["went_offline"] = side.root.evaluate("() => !navigator.onLine")
        facts["uuid"] = side.root.evaluate(_ORDER_UUID)
        facts["validated_offline"] = sell_one(side)
        facts["offline_notice"] = offline_notice(side)
        offline_seen = recorder.details(offline_mark)
    finally:
        side.context.set_offline(False)
    restored = recorder.mark()
    started = time.time()
    rows: list[dict[str, Any]] = []
    while time.time() - started < SYNC_WAIT_S:
        rows = server.rpc("pos.order", "search_read", [[["uuid", "=", facts.get("uuid")]]],
                          {"fields": ["uuid", "session_id", "state", "amount_total", "pos_reference"]})
        if rows:
            facts["synced_after_s"] = round(time.time() - started)
            break
        side.page.wait_for_timeout(3000)
    side.settle()
    sale = sale_outcome(facts, rows, session_id=session_id)
    sale = Outcome(sale.available, sale.result,
                   sum_signals(online_before, recorder.since(restored)),
                   {**sale.details, "offline_window": {k: v for k, v in offline_seen.items() if v},
                    "online_signal_sources": {k: v for k, v in online_details.items() if v}})

    side.context.set_offline(True)
    error = None
    till_loaded = False
    try:
        try:
            side.goto(till, wait="domcontentloaded")
            side.root.locator("article.product, .modal button").first.wait_for(timeout=15_000)
            till_loaded = True
        except Exception as caught:  # noqa: BLE001 -- the failure is the result
            error = str(caught).splitlines()[0] if net_error(str(caught)) else None
    finally:
        side.context.set_offline(False)
    return sale, reload_outcome(error, till_loaded=till_loaded)


# --- Live helpers the shared-layer run uses (#143: U-F5 receipt, U-C25 scan) ---

_ORDER_NAME = """() => {
  const pos = window.posmodel || (odoo.__WOWL_DEBUG__ && odoo.__WOWL_DEBUG__.root.env.services.pos);
  const order = pos.getOrder ? pos.getOrder() : pos.get_order();
  return order.pos_reference || order.name || '';
}"""
# printWeb mounts the receipt in `.render-container`, then calls window.print;
# the stub keeps what would have been printed and prints nothing.
_PRINT_STUB = """() => {
  window.__parityPrint = [];
  window.print = () => {
    const box = document.querySelector('.render-container');
    window.__parityPrint.push({ text: box ? box.innerText : '',
                                images: box ? [...box.querySelectorAll('img')].map(img => img.src) : [] });
  };
}"""
_URL_LOADS = """async (src) => {
  if (src.startsWith('data:')) return true;
  try { return (await fetch(src, { credentials: 'include' })).ok; } catch (error) { return false; }
}"""


def pos_config_id(side: Side, name: str = "Furniture Shop") -> int:
    rows = side.rpc("pos.config", "search_read", [[["name", "=", name]]], {"fields": ["id"]})
    if not rows:
        raise RuntimeError("no pos.config named %r" % name)
    return rows[0]["id"]


def open_till(side: Side, config_id: int) -> None:
    side.close_chat_windows()
    side.goto("%s?config_id=%d" % (ROUTE, config_id), wait="domcontentloaded")
    enter_till(side)
    side.settle()


def print_receipt(side: Side, config_id: int) -> dict[str, Any]:
    """Sell one product and press Print Full Receipt; what print() was given."""
    open_till(side, config_id)
    root = side.root
    name = root.evaluate(_ORDER_NAME)
    root.evaluate(_PRINT_STUB)
    state: dict[str, Any] = {"receipt_shown": sell_one(side), "print_calls": 0}
    if not state["receipt_shown"]:
        return state
    root.locator("button.print", has_text="Print Full Receipt").first.click()
    calls: list[dict[str, Any]] = []
    for _ in range(15):
        calls = root.evaluate("() => window.__parityPrint") or []
        if calls:
            break
        side.page.wait_for_timeout(1000)
    state["print_calls"] = len(calls)
    if calls:
        printed = calls[0]
        state["receipt_chars"] = len(printed["text"])
        state["has_order_name"] = bool(name) and name in printed["text"]
        state["images"] = [{"src": src, "loaded": root.evaluate(_URL_LOADS, src)} for src in printed["images"]]
    return state


def camera_scan(side: Side, config_id: int) -> str:
    """The product screen's barcode button, which opens the camera scanner."""
    open_till(side, config_id)
    control = side.root.locator("button:has(i.fa-barcode)")
    if not control.count():
        return "POS product scan: no camera control"
    control.first.click()
    side.page.wait_for_timeout(3000)
    live = side.root.evaluate("() => [...document.querySelectorAll('video')].some(v => v.srcObject)")
    control.first.click()  # Stop
    return "POS product scan: camera %s" % ("streaming" if live else "not streaming")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--env-file")
    run.add_argument("--db", required=True, help="the database both surfaces must serve")
    run.add_argument("--out", required=True, help="JSONL file; records are appended")
    run.add_argument("--run-id")
    run.add_argument("--config", default="Furniture Shop", help="the pos.config to sell with")
    run.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)

    if args.env_file:
        with open(args.env_file, encoding="utf-8") as handle:
            parse_env_file(handle, os.environ)
    os.environ["ODOO_DB"] = args.db
    env = Env(args.db)
    info = RunInfo(args.run_id or new_run_id(), env.target, env.db)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        public = ingress = None
        try:
            public, ingress = open_sides(env, browser)
            config = public.rpc("pos.config", "search_read", [[["name", "=", args.config]]],
                                {"fields": ["current_session_id", "current_session_state"]})
            if not config or not config[0]["current_session_id"]:
                raise RuntimeError("config %r has no open session" % args.config)
            config_id, session_id = config[0]["id"], config[0]["current_session_id"][0]
            print("session %s (%s)" % (config[0]["current_session_id"][1], config[0]["current_session_state"]),
                  file=sys.stderr)
            outcomes = {}
            for side in (public, ingress):
                try:
                    outcomes[side.name] = offline_sale(side, public, session_id, config_id)
                except Exception as error:  # noqa: BLE001 -- a failure is evidence, as in Run.both
                    side.context.set_offline(False)
                    os.makedirs(artifact_dir(), exist_ok=True)
                    side.page.screenshot(path=os.path.join(artifact_dir(), "%s-pos-%s.png" % (info.run_id, side.name)))
                    failed = Outcome(False, "error: %s" % env.mask((str(error).splitlines() or [""])[0]))
                    outcomes[side.name] = (failed, failed)
                print("%s: %s / %s" % (side.name, outcomes[side.name][0].result, outcomes[side.name][1].result),
                      file=sys.stderr)
            records = pos_records(info, outcomes["public"][0], outcomes["ingress"][0],
                                  outcomes["public"][1], outcomes["ingress"][1])
            with open(args.out, "a", encoding="utf-8") as out:
                for record in records:
                    out.write(json.dumps(env.mask(record), ensure_ascii=False, sort_keys=True) + "\n")
            for record in records:
                print("%s %s" % (record["verdict"], record["control_identity"]), file=sys.stderr)
            return 0
        finally:
            for side in (public, ingress):
                if side is not None:
                    side.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
