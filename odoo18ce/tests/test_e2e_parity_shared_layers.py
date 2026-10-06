#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the shared-layer parity run (#143).

Nothing here opens a browser, a websocket or reads credentials.
"""
import json
import os
import re
import unittest
from unittest import mock

import e2e_parity_outbound_live
import e2e_parity_shared_layers_live
import e2e_pos_offline_live
from e2e_menu_action_adapter import EVIDENCE_SCHEMA, Masker, RunInfo, Surface, parse_env_file
from e2e_parity_shared_layers_live import artifact_dir
from e2e_parity_shared_layers import (
    ACCEPTED,
    CATALOG,
    COVERED,
    INGRESS_PREFIX_DETAIL,
    INJECTION_KINDS,
    INJECTION_WAYS,
    META_REFRESH_NOTE,
    MODULE_SCREENS,
    NOT_RUN,
    Outcome,
    attach_issues,
    capability_upper_bound,
    check_record,
    conservation,
    injection_group,
    injection_verdict,
    injection_ways,
    judge,
    new_tab_verdict,
    planned_checks,
    seo_head_verdict,
    session_cookie_problems,
    sitemap_divergence,
)

RUN = RunInfo(run_id="WOOW-PARITY-20260925T000000Z", target="local", database="example_db")
PREFIX = "/api/hassio_ingress/tok_ABC123"
# The evidence mask a live run writes through: bases, this session's Ingress prefix, its secrets.
MASK = Masker(bases={"<PUBLIC_BASE>": "https://shop.example", "<HA_BASE>": "http://ha.example:8123"},
              ingress_prefix=PREFIX, secrets=("s3cret-password",))


def ok(result: str = "done", **details) -> Outcome:
    return Outcome(available=True, result=result, details=details)


class CatalogTests(unittest.TestCase):
    def test_the_catalog_holds_groups_f_a_b_c_d_e_of_the_parity_plan(self) -> None:
        counts = {}
        for item in CATALOG.values():
            counts[item.group] = counts.get(item.group, 0) + 1
        self.assertEqual(counts, {"F": 5, "A": 10, "B": 8, "C": 27, "D": 8, "E": 7})
        self.assertEqual(CATALOG["U-C4"].root_cause, ("RC-3",))
        self.assertEqual(CATALOG["U-F5"].layer, "L0/L2")
        self.assertEqual(CATALOG["U-D7"].root_cause, ("RC-10",))

    def test_module_screens_name_catalogued_items(self) -> None:
        for item, module, screen in MODULE_SCREENS:
            self.assertIn(item, CATALOG)
            self.assertTrue(module and screen)

    def test_the_plan_runs_every_item_once_plus_each_module_screen(self) -> None:
        plan = planned_checks()
        shared = [item for item in CATALOG.values() if item.group != "E"]
        self.assertEqual(len(plan), len(shared) + len(MODULE_SCREENS))
        self.assertEqual(len(set(plan)), len(plan))
        self.assertIn(("U-C4", "shared", "generic"), plan)
        self.assertIn(("U-C4", "survey", "survey share dialog"), plan)
        self.assertIn(("U-F5", "point_of_sale", "POS receipt print"), plan)
        # U-D8 is two records: the head links plus robots.txt, and the sitemap (AD-8).
        self.assertIn(("U-D8", "shared", "generic"), plan)
        self.assertIn(("U-D8", "website", "sitemap.xml"), plan)


class JudgeTests(unittest.TestCase):
    def test_equal_clean_outcomes_are_parity(self) -> None:
        self.assertEqual(judge(ok(), ok()), ("PARITY", "none", []))

    def test_different_results_are_an_important_gap(self) -> None:
        verdict, severity, reasons = judge(ok("copied"), ok("nothing copied"))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(reasons, ["result: public=copied ingress=nothing copied"])

    def test_an_unavailable_surface_or_an_escape_is_a_blocker(self) -> None:
        down = Outcome(available=False, result="blank page")
        self.assertEqual(judge(ok(), down)[:2], ("GAP", "blocker"))
        escaped = Outcome(available=True, result="done", signals={"route_escape": 1})
        self.assertEqual(judge(ok(), escaped), ("GAP", "blocker", ["ingress route_escape=1"]))

    def test_a_console_error_is_important(self) -> None:
        noisy = Outcome(available=True, result="done", signals={"console_error": 2})
        self.assertEqual(judge(noisy, ok()), ("GAP", "important", ["public console_error=2"]))


class RecordTests(unittest.TestCase):
    def test_a_check_record_has_the_v1_shape_and_both_surfaces(self) -> None:
        record = check_record(RUN, "U-C4", module="survey", screen="survey share dialog",
                              public=ok("copied"), ingress=ok("copied"))
        self.assertEqual(record["schema"], EVIDENCE_SCHEMA)
        self.assertEqual((record["item"], record["layer"], record["root_cause"]), ("U-C4", "L3", ["RC-3"]))
        self.assertEqual(record["screen"], {"route": None, "model": None, "view": None, "name": "survey share dialog"})
        self.assertEqual(record["control_identity"], "check:U-C4|survey|survey share dialog")
        self.assertEqual((record["verdict"], record["severity"]), ("PARITY", "none"))
        self.assertEqual(record["ingress"]["signals"]["route_escape"], 0)
        json.dumps(record)

    def test_an_explicit_verdict_overrides_the_judge(self) -> None:
        record = check_record(RUN, "U-B8", module="shared", screen="generic", public=ok("anonymous"),
                              ingress=ok("401"), verdict="APPROVED-DIVERGENCE", severity="none", notes="AD-6")
        self.assertEqual(record["verdict"], "APPROVED-DIVERGENCE")

    def test_structural_must_name_the_public_origin_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "Public origin path"):
            check_record(RUN, "U-D7", module="website_sale", screen="/shop", public=ok(), ingress=ok(),
                         verdict="STRUCTURAL", severity="none")
        record = check_record(RUN, "U-D7", module="website_sale", screen="/shop", public=ok(), ingress=ok(),
                              verdict="STRUCTURAL", severity="none", public_path="<PUBLIC_BASE>/shop")
        self.assertEqual(record["public_path"], "<PUBLIC_BASE>/shop")

    def test_not_run_must_name_its_blocker(self) -> None:
        with self.assertRaisesRegex(ValueError, "blocked_by"):
            check_record(RUN, "U-F5", module="point_of_sale", screen="POS receipt print",
                         public=None, ingress=None, verdict=NOT_RUN)
        record = check_record(RUN, "U-F5", module="point_of_sale", screen="POS receipt print",
                              public=None, ingress=None, verdict=NOT_RUN, blocked_by="#161")
        self.assertEqual((record["verdict"], record["severity"], record["blocked_by"]), (NOT_RUN, None, "#161"))
        self.assertIsNone(record["public"])

    def test_an_unknown_verdict_or_item_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            check_record(RUN, "U-C4", module="shared", screen="generic", public=ok(), ingress=ok(), verdict="PASS")
        with self.assertRaises(KeyError):
            check_record(RUN, "U-Z9", module="shared", screen="generic", public=ok(), ingress=ok())


class CapabilityTests(unittest.TestCase):
    ALL = ["clipboard-write", "fullscreen", "camera", "microphone"]

    def test_an_unrestricted_frame_in_a_secure_context_can_do_everything(self) -> None:
        bound = capability_upper_bound({"allow": None, "sandbox": None}, self.ALL, secure_context=True)
        self.assertTrue(all(entry["usable"] for entry in bound.values()))
        self.assertEqual(sorted(bound), ["camera", "clipboard-write", "downloads", "fullscreen", "microphone"])

    def test_an_insecure_context_blocks_only_the_secure_context_features(self) -> None:
        bound = capability_upper_bound({"allow": None, "sandbox": None}, self.ALL, secure_context=False)
        self.assertEqual({name for name, entry in bound.items() if not entry["usable"]},
                         {"clipboard-write", "camera", "microphone"})
        self.assertEqual(bound["camera"], {"policy": True, "usable": False, "limit": "insecure context"})
        self.assertEqual(bound["fullscreen"], {"policy": True, "usable": True, "limit": None})

    def test_the_iframe_policy_and_sandbox_are_limits_of_their_own(self) -> None:
        bound = capability_upper_bound({"allow": "fullscreen", "sandbox": "allow-scripts"}, ["fullscreen"],
                                       secure_context=True)
        self.assertEqual(bound["camera"]["limit"], "iframe policy")
        self.assertEqual(bound["downloads"], {"policy": False, "usable": False, "limit": "iframe sandbox"})
        sandboxed = capability_upper_bound({"sandbox": "allow-scripts allow-downloads"}, [], secure_context=True)
        self.assertTrue(sandboxed["downloads"]["usable"])


class CookieTests(unittest.TestCase):
    def cookie(self, **overrides) -> dict:
        values = {"name": "session_id", "path": PREFIX + "/", "secure": False, "httpOnly": True, "sameSite": "Lax"}
        values.update(overrides)
        return values

    def test_the_ingress_cookie_is_scoped_to_the_prefix(self) -> None:
        self.assertEqual(session_cookie_problems(self.cookie(), surface=Surface.HA_INGRESS,
                                                 ingress_prefix=PREFIX, https=False), [])
        self.assertEqual(session_cookie_problems(self.cookie(path="/"), surface=Surface.HA_INGRESS,
                                                 ingress_prefix=PREFIX, https=False),
                         ["Path=/ (expected %s/)" % PREFIX])

    def test_secure_follows_the_scheme(self) -> None:
        self.assertEqual(session_cookie_problems(self.cookie(), surface=Surface.HA_INGRESS,
                                                 ingress_prefix=PREFIX, https=True),
                         ["Secure=False (expected True)"])

    def test_the_public_cookie_is_root_scoped_and_secure(self) -> None:
        public = self.cookie(path="/", secure=True)
        self.assertEqual(session_cookie_problems(public, surface=Surface.PUBLIC, ingress_prefix=None, https=True), [])
        self.assertEqual(
            session_cookie_problems(dict(public, httpOnly=False, sameSite="None"), surface=Surface.PUBLIC,
                                    ingress_prefix=None, https=True),
            ["HttpOnly=False (expected True)", "SameSite=None (expected Lax)"],
        )

    def test_a_missing_cookie_is_one_problem(self) -> None:
        self.assertEqual(session_cookie_problems(None, surface=Surface.PUBLIC, ingress_prefix=None, https=True),
                         ["no session_id cookie"])


class InjectionWayTests(unittest.TestCase):
    """U-A6 as two groups (#169): the ways the shim covers, and the ways it does not."""

    def ways(self, *escaped: str, not_requested: tuple[str, ...] = ()) -> Outcome:
        requested = [kind for kind in INJECTION_KINDS if kind not in not_requested]
        return Outcome(available=True,
                       result="no escape" if not escaped else "escaped: " + ", ".join(sorted(escaped)),
                       details={"requested": sorted(requested), "escaped": sorted(escaped),
                                "not_requested": sorted(not_requested),
                                "groups": {kind: injection_group(kind) for kind in INJECTION_KINDS}})

    def test_every_way_the_check_tries_is_in_one_group(self) -> None:
        self.assertEqual(sorted(INJECTION_KINDS), sorted(injection_ways(COVERED) + injection_ways(ACCEPTED)))
        self.assertEqual(injection_ways(COVERED),
                         ["sendBeacon", "EventSource", "svg-use", "svg-use-href", "svg-use-ns", "media"])
        # An accepted way is a decision, so the screens it is known to hit are named with it.
        issues = {way.kind: way.issues for way in INJECTION_WAYS}
        self.assertEqual(issues["innerHTML-img"], ("#158",))
        self.assertEqual(issues["style-attr"], ("#170",))
        # A way with no screen filed against it names none; the group is the decision.
        self.assertEqual(issues["insertAdjacentHTML-use"], ())
        # A covered way is the shim's job, not a per-screen escape, so it names no issue -- media
        # included, though #159 is what made it covered.
        self.assertEqual([way.issues for way in INJECTION_WAYS if way.group == COVERED], [()] * 6)

    def test_no_escape_on_either_surface_is_parity(self) -> None:
        self.assertEqual(injection_verdict(self.ways(), self.ways()), ("PARITY", "none", []))

    def test_a_covered_way_escaping_under_ingress_is_a_gap(self) -> None:
        verdict, severity, notes = injection_verdict(self.ways(), self.ways("sendBeacon", "svg-use"))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(notes, ["ingress: the shim did not prefix sendBeacon (navigator.sendBeacon(url)), "
                                 "svg-use (createElementNS <use>, an existing xlink:href updated with "
                                 'setAttribute("xlink:href", url))'])

    def test_an_accepted_way_escaping_under_ingress_stays_parity_with_its_screens(self) -> None:
        verdict, severity, notes = injection_verdict(self.ways(), self.ways("innerHTML-img", "style-attr",
                                                                            "css-import"))
        self.assertEqual((verdict, severity), ("PARITY", "none"))
        self.assertEqual(notes, ["accepted escapes, uncovered by decision: "
                                 "css-import, innerHTML-img (#158), style-attr (#170)"])

    def test_a_covered_escape_beside_an_accepted_one_is_still_a_gap(self) -> None:
        verdict, _, notes = injection_verdict(self.ways(), self.ways("EventSource", "style-url"))
        self.assertEqual(verdict, "GAP")
        self.assertEqual(notes, ["ingress: the shim did not prefix EventSource (new EventSource(url))",
                                 "accepted escapes, uncovered by decision: style-url"])

    def test_any_escape_on_the_public_origin_is_a_gap(self) -> None:
        # The Public origin has no prefix to lose, so an accepted way escaping there is
        # a root-relative URL leaving the origin it was asked from: a defect on both.
        verdict, severity, notes = injection_verdict(self.ways("innerHTML-img"), self.ways())
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(notes, ["public: a root-relative URL left the origin through innerHTML-img"])

    def test_a_way_no_decision_knows_is_covered(self) -> None:
        self.assertEqual(injection_group("meta-refresh"), COVERED)
        verdict, _, notes = injection_verdict(self.ways(), self.ways("meta-refresh"))
        self.assertEqual(verdict, "GAP")
        self.assertEqual(notes, ["ingress: the shim did not prefix meta-refresh"])

    def test_a_covered_way_that_made_no_request_is_named_not_judged(self) -> None:
        verdict, severity, notes = injection_verdict(self.ways(), self.ways(not_requested=("EventSource",
                                                                                           "css-import")))
        self.assertEqual((verdict, severity), ("PARITY", "none"))
        self.assertEqual(notes, ["covered ways the browser never asked for: EventSource"])

    def test_an_unavailable_surface_is_still_a_blocker(self) -> None:
        verdict, severity, notes = injection_verdict(self.ways(), Outcome(available=False, result="blank page"))
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(notes, ["ingress unavailable: blank page"])

    def test_the_live_probe_asks_the_covered_ways_through_the_apis_the_shim_hooks(self) -> None:
        script = e2e_parity_shared_layers_live._INJECTION_JS
        for api in ("navigator.sendBeacon(probe('sendBeacon')", "new EventSource(probe('EventSource')",
                    "createElementNS(SVG, 'use')", "node.setAttribute('xlink:href', url)",
                    "node.setAttributeNS(XLINK, 'xlink:href', '#seed')",
                    "node.setAttribute('href', url)", "node.setAttributeNS(XLINK, 'xlink:href', url)"):
            self.assertIn(api, script)
        # The accepted ways stay markup and style, including the style attribute #170 hits.
        for markup in ("markup.innerHTML =", "markup.insertAdjacentHTML(", "inline.setAttribute('style',",
                       "style.textContent =", "@import url("):
            self.assertIn(markup, script)
        # Every way the groups declare is probed, and nothing else is.
        probed = set(re.findall(r"(?:probe|use)\('([A-Za-z-]+)'", script))
        self.assertEqual(probed, set(INJECTION_KINDS))
        self.assertIn("http-equiv=refresh", META_REFRESH_NOTE)


class SeoOutputTests(unittest.TestCase):
    """U-D8 as two decisions: the head links with `robots.txt`, and the sitemap (AD-8)."""

    def head(self, *wrong: str) -> Outcome:
        bases = ["<PUBLIC_BASE>", *(base for base in wrong if base.startswith("<"))]
        return Outcome(available=True, details={"bases": sorted(set(bases)), "wrong": list(wrong)},
                       result="all SEO URLs on <PUBLIC_BASE>" if not wrong else "SEO URLs on %s" % ", ".join(wrong))

    def test_head_links_on_the_canonical_url_on_both_surfaces_are_parity(self) -> None:
        self.assertEqual(seo_head_verdict(self.head(), self.head()), ("PARITY", "none", []))

    def test_a_base_that_is_not_the_canonical_url_is_a_gap(self) -> None:
        verdict, severity, reasons = seo_head_verdict(self.head(), self.head("<HA_BASE>"))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(reasons, ["result: public=all SEO URLs on <PUBLIC_BASE> ingress=SEO URLs on <HA_BASE>",
                                   "ingress SEO URLs on <HA_BASE>"])

    def test_both_surfaces_wrong_in_the_same_way_is_still_a_gap(self) -> None:
        # judge() sees two equal results; U-D8's PASS rule is absolute, as in group E.
        verdict, severity, reasons = seo_head_verdict(self.head("relative URLs"), self.head("relative URLs"))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(reasons, ["public SEO URLs on relative URLs", "ingress SEO URLs on relative URLs"])

    def test_an_unavailable_surface_stays_a_blocker(self) -> None:
        down = Outcome(available=False, result="error: blank page")
        self.assertEqual(seo_head_verdict(self.head(), down)[:2], ("GAP", "blocker"))

    ROBOTS = ("User-agent: *", "Disallow: /", "Sitemap: <PUBLIC_BASE>/sitemap.xml")
    PUBLIC_ROBOTS = ("User-agent: *", "Sitemap: <PUBLIC_BASE>/sitemap.xml")

    def sitemap(self, *, public=("<PUBLIC_BASE>",), ingress=("<HA_BASE>",), robots=ROBOTS,
                public_robots=PUBLIC_ROBOTS, status=200, prefixed=0, available=True) -> tuple[Outcome, Outcome]:
        def side(bases, robots_lines) -> Outcome:
            return Outcome(available=available, result="%d sitemap URL(s) on %s" % (len(bases),
                                                                                   ", ".join(bases) or "nothing"),
                           details={"bases": list(bases), "status": status, "robots": list(robots_lines)})
        public_side, ingress_side = side(public, public_robots), side(ingress, robots)
        if prefixed:
            ingress_side = Outcome(available, ingress_side.result,
                                   details={**ingress_side.details, "ingress_prefix": prefixed})
        return public_side, ingress_side

    def test_the_ingress_sitemap_following_the_request_address_is_ad_8(self) -> None:
        self.assertEqual(sitemap_divergence(*self.sitemap()), ("APPROVED-DIVERGENCE", "none", []))

    def test_a_robots_txt_that_no_longer_steers_crawlers_is_a_gap(self) -> None:
        verdict, severity, reasons = sitemap_divergence(*self.sitemap(robots=("User-agent: *",)))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(reasons, ["ingress robots.txt has no 'Disallow: /'",
                                   "ingress robots.txt has no 'Sitemap: <PUBLIC_BASE>/sitemap.xml'"])
        # An empty website.domain (P-5) is exactly this: no Disallow, and the sitemap line follows the request.
        self.assertEqual(sitemap_divergence(*self.sitemap(
            robots=("User-agent: *", "Sitemap: <HA_BASE>/sitemap.xml")))[2],
            ["ingress robots.txt has no 'Disallow: /'",
             "ingress robots.txt has no 'Sitemap: <PUBLIC_BASE>/sitemap.xml'"])

    def test_the_divergence_disappearing_is_a_gap_too(self) -> None:
        verdict, _, reasons = sitemap_divergence(*self.sitemap(ingress=("<PUBLIC_BASE>",)))
        self.assertEqual(verdict, "GAP")
        self.assertEqual(reasons, ["ingress sitemap on <PUBLIC_BASE>: AD-8 no longer holds"])

    def test_the_public_origin_sitemap_must_stay_on_the_canonical_url_and_crawlable(self) -> None:
        self.assertEqual(sitemap_divergence(*self.sitemap(public=("<HA_BASE>",)))[2],
                         ["public sitemap on <HA_BASE>"])
        self.assertEqual(sitemap_divergence(*self.sitemap(public=()))[2], ["public sitemap on nothing"])
        self.assertEqual(sitemap_divergence(*self.sitemap(public_robots=("Disallow: /",)))[2],
                         ["public robots.txt says 'Disallow: /'"])

    def test_a_sitemap_with_no_url_at_all_is_a_gap(self) -> None:
        self.assertEqual(sitemap_divergence(*self.sitemap(ingress=()))[2], ["ingress sitemap has no URL"])

    def test_a_sitemap_that_was_not_served_is_a_gap(self) -> None:
        verdict, severity, reasons = sitemap_divergence(*self.sitemap(status=404))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(reasons[:2], ["public sitemap.xml HTTP 404", "ingress sitemap.xml HTTP 404"])

    def test_an_ingress_prefix_inside_the_sitemap_is_a_blocker(self) -> None:
        verdict, severity, reasons = sitemap_divergence(*self.sitemap(prefixed=3))
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons, ["ingress sitemap carries the Ingress prefix in 3 URL(s)"])

    def test_an_unavailable_surface_is_a_blocker_not_an_approved_divergence(self) -> None:
        verdict, severity, reasons = sitemap_divergence(*self.sitemap(available=False))
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons[:2], ["public unavailable: 1 sitemap URL(s) on <PUBLIC_BASE>",
                                       "ingress unavailable: 1 sitemap URL(s) on <HA_BASE>"])

    def test_both_u_d8_records_reconcile_with_no_remainder(self) -> None:
        plan = [("U-D8", "shared", "generic"), ("U-D8", "website", "sitemap.xml")]
        public, ingress = self.sitemap()
        records = [
            check_record(RUN, "U-D8", module="shared", screen="generic", public=self.head(), ingress=self.head()),
            check_record(RUN, "U-D8", module="website", screen="sitemap.xml", public=public, ingress=ingress,
                         verdict="APPROVED-DIVERGENCE", severity="none", notes="AD-8"),
        ]
        report = conservation(records, plan)
        self.assertTrue(report["qualified"], report)
        self.assertEqual(report["counts"]["PARITY"], 1)
        self.assertEqual(report["counts"]["APPROVED-DIVERGENCE"], 1)


class NewTabTests(unittest.TestCase):
    """U-C23: a tab Odoo opens in the browser, and where its address lands.

    The shapes are the ones the #143 run recorded (`check:U-C23|shared|generic`,
    run `WOOW-PARITY-20260925T043539Z`): the survey's Test button.
    """

    PAGE = "This is a Test Survey Entry.\n\nGo to Survey"
    PUBLIC_SHAPE = "<PUBLIC_BASE>/survey/<token>"
    INGRESS_SHAPE = "<HA_BASE><INGRESS_PREFIX>/survey/<token>"

    def tab(self, shape: str, page_text: str | None = None) -> Outcome:
        text = self.PAGE if page_text is None else page_text
        carries = "<INGRESS_PREFIX>" in shape
        return Outcome(available=True,
                       details={"shape": shape, "page_text": text, INGRESS_PREFIX_DETAIL: carries},
                       result="new tab at %s%s" % (shape, " (carries the Ingress token)" if carries else ""))

    def pair(self, *, public: str | None = None, ingress: str | None = None,
             public_text: str | None = None, ingress_text: str | None = None) -> tuple[Outcome, Outcome]:
        return (self.tab(public or self.PUBLIC_SHAPE, public_text),
                self.tab(ingress or self.INGRESS_SHAPE, ingress_text))

    def test_the_same_page_under_the_ingress_prefix_is_structural(self) -> None:
        self.assertEqual(new_tab_verdict(*self.pair()),
                         ("STRUCTURAL", "none", [], "<PUBLIC_BASE>/survey/<token>"))

    def test_a_tab_that_did_not_open_stays_a_gap(self) -> None:
        public, _ = self.pair()
        down = Outcome(available=False, result="error at survey Test button: Timeout 20000ms exceeded")
        verdict, severity, reasons, public_path = new_tab_verdict(public, down)
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons, ["ingress unavailable: error at survey Test button: Timeout 20000ms exceeded"])
        self.assertIsNone(public_path)

    def test_an_ingress_tab_off_the_prefix_is_a_gap(self) -> None:
        verdict, severity, reasons, public_path = new_tab_verdict(*self.pair(ingress="<HA_BASE>/survey/<token>"))
        self.assertEqual((verdict, severity), ("GAP", "important"))
        self.assertEqual(reasons, ["ingress tab at <HA_BASE>/survey/<token>, "
                                   "not under <HA_BASE><INGRESS_PREFIX>"])
        self.assertIsNone(public_path)

    def test_a_public_tab_off_the_canonical_url_is_a_gap(self) -> None:
        self.assertEqual(new_tab_verdict(*self.pair(public="<HA_BASE>/survey/<token>"))[2],
                         ["public tab at <HA_BASE>/survey/<token>, not under <PUBLIC_BASE>"])

    def test_two_tabs_on_different_pages_are_a_gap(self) -> None:
        verdict, _, reasons, _ = new_tab_verdict(*self.pair(ingress="<HA_BASE><INGRESS_PREFIX>/odoo/survey"))
        self.assertEqual(verdict, "GAP")
        self.assertEqual(reasons, ["the tabs opened different pages: public /survey/<token>, ingress /odoo/survey"])
        self.assertEqual(new_tab_verdict(*self.pair(ingress_text="Internal Server Error"))[2],
                         ["the two tabs do not render the same page"])

    def test_a_tab_with_nothing_in_it_is_a_blank_screen_and_a_blocker(self) -> None:
        verdict, severity, reasons, _ = new_tab_verdict(*self.pair(public_text="", ingress_text=""))
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons, ["public tab rendered no text", "ingress tab rendered no text"])

    def test_the_ingress_prefix_in_the_public_tab_address_is_a_leak_and_a_blocker(self) -> None:
        # Section 1.3: an Ingress token in an outbound address is a Blocker, not an Important.
        verdict, severity, reasons, public_path = new_tab_verdict(
            *self.pair(public="<PUBLIC_BASE><INGRESS_PREFIX>/survey/<token>"))
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons, ["public tab address carries the Ingress prefix"])
        self.assertIsNone(public_path)

    def test_the_shape_alone_shows_the_leak_when_the_flag_says_nothing(self) -> None:
        # A record with no flag at all -- one written before #187, re-judged from the file --
        # still has its address in `shape`, and that is enough to see the prefix.
        public, ingress = self.pair(public="<PUBLIC_BASE><INGRESS_PREFIX>/survey/<token>")
        flagless = Outcome(available=True, result=public.result,
                           details={key: value for key, value in public.details.items()
                                    if key != INGRESS_PREFIX_DETAIL})
        self.assertEqual(new_tab_verdict(flagless, ingress)[:3],
                         ("GAP", "blocker", ["public tab address carries the Ingress prefix"]))

    def test_a_token_the_mask_did_not_recognise_is_a_leak_too(self) -> None:
        # A prefix that is not this session's own (#160) survives masking; it is still a token.
        leaked = Outcome(available=True, result="new tab at <PUBLIC_BASE>/api/hassio_ingress/xyz/survey/<token>",
                         details={"shape": "<PUBLIC_BASE>/api/hassio_ingress/xyz/survey/<token>",
                                  "page_text": self.PAGE})
        _, ingress = self.pair()
        verdict, severity, reasons, _ = new_tab_verdict(leaked, ingress)
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons, ["public tab address carries the Ingress prefix"])

    def test_a_token_only_in_the_query_is_a_leak_the_probe_reports(self) -> None:
        # The shape holds the path alone, so the probe flags a prefix anywhere in the address.
        public, ingress = self.pair()
        leaked = Outcome(available=True, result=public.result,
                         details={**public.details, INGRESS_PREFIX_DETAIL: True})
        self.assertEqual(new_tab_verdict(leaked, ingress)[:3],
                         ("GAP", "blocker", ["public tab address carries the Ingress prefix"]))

    def test_a_route_escape_under_ingress_is_a_blocker(self) -> None:
        public, ingress = self.pair()
        escaped = Outcome(True, ingress.result, signals={"route_escape": 1}, details=dict(ingress.details))
        verdict, severity, reasons, _ = new_tab_verdict(public, escaped)
        self.assertEqual((verdict, severity), ("GAP", "blocker"))
        self.assertEqual(reasons, ["ingress route_escape=1"])

    def test_the_structural_record_names_the_public_origin_path(self) -> None:
        verdict, severity, _, public_path = new_tab_verdict(*self.pair())
        record = check_record(RUN, "U-C23", module="shared", screen="generic", public=self.tab(self.PUBLIC_SHAPE),
                             ingress=self.tab(self.INGRESS_SHAPE), verdict=verdict, severity=severity,
                             public_path=public_path, model="survey.survey")
        self.assertEqual(record["verdict"], "STRUCTURAL")
        self.assertEqual(record["severity"], "none")
        self.assertEqual(record["root_cause"], ["RC-15"])
        self.assertEqual(record["public_path"], "<PUBLIC_BASE>/survey/<token>")

    def test_the_recorded_record_says_which_tab_carried_the_ingress_prefix(self) -> None:
        # #187: the flag was `details["ingress_token"]`, and the evidence mask redacts every
        # value under a key that reads as a secret -- so both sides wrote `<redacted>` and the
        # file could not say which tab carried the prefix. The name is what fixed that.
        verdict, severity, _, public_path = new_tab_verdict(*self.pair())
        record = check_record(RUN, "U-C23", module="shared", screen="generic", public=self.tab(self.PUBLIC_SHAPE),
                              ingress=self.tab(self.INGRESS_SHAPE), verdict=verdict, severity=severity,
                              public_path=public_path, model="survey.survey")
        written = json.loads(json.dumps(MASK.value(record), sort_keys=True))
        self.assertIs(written["public"]["details"][INGRESS_PREFIX_DETAIL], False)
        self.assertIs(written["ingress"]["details"][INGRESS_PREFIX_DETAIL], True)

    def test_the_mask_still_redacts_a_secret_bearing_string(self) -> None:
        # The fail-safe the rename must not weaken: a value under a secret-bearing key, a
        # credential of this session, and a foreign Ingress token in a plain string all go.
        masked = MASK.value({"session_token": "not-listed-anywhere", "authorization": "Bearer abc",
                             "note": "logged in as admin with s3cret-password",
                             "url": "https://other.example/api/hassio_ingress/deadbeefcafe/odoo"})
        self.assertEqual(masked["session_token"], "<redacted>")
        self.assertEqual(masked["authorization"], "<redacted>")
        self.assertEqual(masked["note"], "logged in as admin with <redacted>")
        self.assertEqual(masked["url"], "https://other.example/api/hassio_ingress/<redacted>/odoo")

    def test_a_flag_that_is_not_a_boolean_is_unknown_not_a_leak(self) -> None:
        # Nothing re-judges a record read back from a file today; when something does, a masked
        # or missing flag must not invent a Blocker. Only a real `bool` is evidence.
        public, ingress = self.pair()
        for flag in ("<redacted>", "True", 1, None):
            with self.subTest(flag=flag):
                details = {key: value for key, value in public.details.items()
                           if key != INGRESS_PREFIX_DETAIL}
                if flag is not None:
                    details[INGRESS_PREFIX_DETAIL] = flag
                read_back = Outcome(available=True, result=public.result, details=details)
                self.assertEqual(new_tab_verdict(read_back, ingress),
                                 ("STRUCTURAL", "none", [], "<PUBLIC_BASE>/survey/<token>"))


class ConservationTests(unittest.TestCase):
    PLAN = [("U-C4", "shared", "generic"), ("U-C4", "survey", "survey share dialog"), ("U-F5", "shared", "generic")]

    def records(self) -> list:
        return [
            check_record(RUN, "U-C4", module="shared", screen="generic", public=ok(), ingress=ok()),
            check_record(RUN, "U-C4", module="survey", screen="survey share dialog",
                         public=ok("copied"), ingress=ok("nothing")),
            check_record(RUN, "U-F5", module="shared", screen="generic", public=None, ingress=None,
                         verdict=NOT_RUN, blocked_by="#161"),
        ]

    def test_counts_add_up_to_the_observed_total(self) -> None:
        report = conservation(self.records(), self.PLAN)
        self.assertEqual(report["observed"], 3)
        self.assertEqual(report["counts"], {"PARITY": 1, "GAP": 1, "APPROVED-DIVERGENCE": 0, "STRUCTURAL": 0,
                                            NOT_RUN: 1})
        self.assertEqual(report["missing"], [])

    def test_a_gap_without_an_issue_or_a_not_run_disqualifies_the_run(self) -> None:
        report = conservation(self.records(), self.PLAN)
        self.assertFalse(report["qualified"])
        self.assertEqual(report["gaps_without_issue"], ["check:U-C4|survey|survey share dialog"])
        self.assertEqual(report["not_run"], ["check:U-F5|shared|generic"])

    def test_missing_and_unplanned_checks_are_listed(self) -> None:
        report = conservation(self.records()[:2], self.PLAN + [("U-D1", "shared", "generic")])
        self.assertEqual(report["missing"], ["check:U-D1|shared|generic", "check:U-F5|shared|generic"])
        extra = check_record(RUN, "U-D2", module="shared", screen="generic", public=ok(), ingress=ok())
        self.assertEqual(conservation(self.records() + [extra], self.PLAN)["unplanned"],
                         ["check:U-D2|shared|generic"])

    def test_a_run_with_every_gap_filed_and_nothing_left_out_qualifies(self) -> None:
        records = attach_issues(self.records()[:2], {"check:U-C4|survey|survey share dialog": 170})
        self.assertEqual(records[1]["issue"], "#170")
        report = conservation(records, self.PLAN[:2])
        self.assertTrue(report["qualified"], report)

    def test_attaching_an_issue_to_a_record_that_is_not_a_gap_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a GAP"):
            attach_issues(self.records(), {"check:U-C4|shared|generic": 170})


class LiveHelperTests(unittest.TestCase):
    """Pure helpers of the Live module; importing it opens no browser."""

    def test_path_tokens_are_masked_everywhere(self) -> None:
        from e2e_parity_shared_layers_live import _mask_tokens

        value = {"a": ["<PUBLIC_BASE>/survey/start/fd2b63b2-c0a7-4d71-9e52-bbf91e663dd7",
                       "/hr_attendance/0123456789abcdef0123456789abcdef"], "n": 3}
        self.assertEqual(_mask_tokens(value), {"a": ["<PUBLIC_BASE>/survey/start/<token>", "/hr_attendance/<token>"],
                                               "n": 3})
        self.assertEqual(_mask_tokens("S00001 /odoo/res.partner/9"), "S00001 /odoo/res.partner/9")

    def test_pdf_link_targets_are_read_from_uri_annotations(self) -> None:
        from e2e_parity_shared_layers_live import pdf_urls

        data = b"%PDF-1.4 << /A << /S /URI /URI (https://example.test/terms) >> >> /URI(https://example.test/terms)"
        self.assertEqual(pdf_urls(data), ["https://example.test/terms"])

    def test_xlsx_rows_counts_the_first_sheet(self) -> None:
        import io
        import zipfile

        from e2e_parity_shared_layers_live import xlsx_rows

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", '<sheetData><row r="1"/><row r="2"/></sheetData>')
        self.assertEqual(xlsx_rows(buffer.getvalue()), 2)


class LiveMaskTests(unittest.TestCase):
    ENVIRON = {"ODOO_PUBLIC_URL": "https://odoo.example.test", "HA_BASE_URL": "http://10.1.2.3:8123",
               "HA_HTTPS_BASE_URL": "https://ha.example.test", "HA_TOKEN": "tok-SECRET-123",
               "ADDON_SLUG": "abc_odoo18ce", "ODOO_TEST_LOGIN": "tester@example.test",
               "ODOO_TEST_PASSWORD": "pw-SECRET-456"}

    def env(self):
        from unittest import mock

        from e2e_parity_shared_layers_live import Env

        with mock.patch.dict("os.environ", self.ENVIRON, clear=False):
            env = Env("example_db")
        env.prefix = PREFIX
        return env

    def test_bases_hosts_prefix_and_credentials_are_masked(self) -> None:
        env = self.env()
        text = ("http://10.1.2.3:8123%s/odoo https://odoo.example.test/shop https://ha.example.test/x "
                "ws://10.1.2.3:8123/api/websocket host 10.1.2.3 and ha.example.test "
                "tok-SECRET-123 tester@example.test pw-SECRET-456" % PREFIX)
        masked = env.mask({"notes": text})["notes"]
        for secret in ("10.1.2.3", "odoo.example.test", "ha.example.test", "tok-SECRET-123", "tester@example.test",
                       "pw-SECRET-456", "tok_ABC123"):
            self.assertNotIn(secret, masked)
        self.assertIn("<INGRESS_BASE>/odoo", masked)
        self.assertIn("<PUBLIC_BASE>/shop", masked)
        self.assertIn("<HA_HTTPS_BASE>/x", masked)
        self.assertIn("<HA_HOST>", masked)
        self.assertIn("<HA_HTTPS_HOST>", masked)


class ScreenRecordTests(unittest.TestCase):
    def recorded(self, public: str, ingress: str) -> dict:
        from e2e_parity_shared_layers_live import record_screen

        written = []

        class FakeRun:
            def record(self, item, module, screen, public, ingress, **kwargs):
                written.append(check_record(RUN, item, module=module, screen=screen, public=public,
                                            ingress=ingress, **kwargs))

        record_screen(FakeRun(), "U-C25", "mrp", "MRP work order scan", ok(public), ok(ingress), "camera")
        return written[0]

    def test_a_screen_without_the_control_tested_nothing(self) -> None:
        record = self.recorded("scan: no camera control", "scan: no camera control")
        self.assertEqual(record["verdict"], NOT_RUN)
        self.assertIn("no camera control", record["blocked_by"])

    def test_a_screen_with_the_control_is_judged(self) -> None:
        self.assertEqual(self.recorded("scan: camera streaming", "scan: camera streaming")["verdict"], "PARITY")
        self.assertEqual(self.recorded("scan: camera streaming", "scan: no camera control")["verdict"], "GAP")


class ArtifactDirTests(unittest.TestCase):
    """#188: the artifact directory is resolved when used, after --env-file is parsed."""

    def test_a_name_set_by_the_environment_file_reaches_the_artifact_directory(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop("E2E_ARTIFACT_DIR", None)
            parse_env_file(["E2E_ARTIFACT_DIR=/home/agent/e2e-artifacts"], os.environ)
            self.assertEqual(artifact_dir(), "/home/agent/e2e-artifacts")

    def test_without_a_name_the_default_stays_out_of_the_checkout(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop("E2E_ARTIFACT_DIR", None)
            self.assertEqual(artifact_dir(), "/tmp/odoo-parity-artifacts")

    def test_no_parity_script_binds_the_directory_at_import(self) -> None:
        for module in (e2e_parity_shared_layers_live, e2e_parity_outbound_live, e2e_pos_offline_live):
            self.assertFalse(hasattr(module, "ARTIFACTS"), module.__name__)

    def test_main_parses_the_environment_file_before_the_first_directory_use(self) -> None:
        import inspect

        for module in (e2e_parity_shared_layers_live, e2e_parity_outbound_live, e2e_pos_offline_live):
            source = inspect.getsource(module.main)
            self.assertLess(source.index("parse_env_file"), source.index("artifact_dir()"), module.__name__)

    def test_the_fixture_and_plan_paths_follow_the_environment_at_call_time(self) -> None:
        with mock.patch.dict(os.environ, {"E2E_ARTIFACT_DIR": "/tmp/elsewhere"}):
            self.assertEqual(e2e_parity_shared_layers_live.fixture_path("R1"), "/tmp/elsewhere/R1-fixtures.json")
            self.assertEqual(e2e_parity_outbound_live.fixture_path("R1"), "/tmp/elsewhere/R1-outbound-fixtures.json")
            self.assertEqual(e2e_parity_outbound_live.reach_path("R1"), "/tmp/elsewhere/R1-reach.json")
            self.assertEqual(e2e_parity_outbound_live.mail_plan_path("R1"), "/tmp/elsewhere/R1-mail-plan.json")


class NoWaitRootTests(unittest.TestCase):
    """#288: `Side.root_now`, the resolve that never waits for a panel to load.

    `root` on `IngressSide` is a *search*: the moment the held frame reports
    detached it re-enters `_find_frame(wait_s=60)`, which is 120 iterations of a
    500 ms wait before it raises. That is right for the case it was written for,
    an add-on panel still loading, and wrong on a recovery path running ahead of
    a record's only restore -- there the frame going is why the caller is in the
    recovery path at all. So the waits are what these tests count.
    """

    class FakeFrame:
        def __init__(self, url: str, parent=None, detached: bool = False) -> None:
            self.url = url
            self.parent_frame = parent
            self._detached = detached

        def is_detached(self) -> bool:
            return self._detached

    class FakePage:
        """A Home Assistant page with an add-on panel, and a wait that counts.

        `frames` is a property for the same reason: entering the frame search at
        all is the cost this issue is about, so reading the list is counted too.
        """

        def __init__(self, ingress_frames=()) -> None:
            self.main_frame = NoWaitRootTests.FakeFrame("http://ha.test/slug")
            self._frames = [self.main_frame, *ingress_frames]
            self.waits = 0
            self.frame_reads = 0

        @property
        def frames(self):
            self.frame_reads += 1
            return self._frames

        def wait_for_timeout(self, ms: int) -> None:
            self.waits += 1

    def ingress_side(self, page, held=None):
        """An `IngressSide` with no browser behind it: only `page` and `_frame`.

        Built without `__init__`, which opens a browser context. Everything the
        two resolves touch is set here, and nothing else is reachable from them.
        """
        side = e2e_parity_shared_layers_live.IngressSide.__new__(
            e2e_parity_shared_layers_live.IngressSide)
        side.page = page
        side._frame = held
        return side

    def test_a_detached_held_frame_comes_back_with_no_wait_at_all(self) -> None:
        """The interrupt scenario: the panel navigated, the Ingress iframe went,
        the Home Assistant page is still alive. `root_now` hands back the frame
        the side is holding without asking whether it is detached and without
        entering the search, so the caller's first locator call raises at once
        instead of a minute later."""
        page = self.FakePage()
        held = self.FakeFrame("http://ha.test/api/hassio_ingress/tok/odoo",
                              parent=page.main_frame, detached=True)
        side = self.ingress_side(page, held=held)
        self.assertIs(side.root_now, held)
        self.assertEqual(page.waits, 0)
        self.assertEqual(page.frame_reads, 0)

    def test_the_waiting_resolve_on_the_same_side_spends_the_whole_sweep(self) -> None:
        """What `root_now` is measured against, and why it is a second property
        rather than a change to the first: with the held frame detached and no
        replacement to find, `root` is 120 iterations of a 500 ms wait -- 60 s --
        and then raises, which the discard seam's outer `except` swallows into no
        reading at all."""
        page = self.FakePage()
        held = self.FakeFrame("http://ha.test/api/hassio_ingress/tok/odoo",
                              parent=page.main_frame, detached=True)
        side = self.ingress_side(page, held=held)
        with self.assertRaises(RuntimeError):
            side.root
        self.assertEqual(page.waits, 120)

    def test_a_detached_held_frame_is_not_swapped_for_the_replacement(self) -> None:
        """The reading, not only the wait. A panel that re-mounted has a *new*
        Ingress iframe, and `root` resolves to it with no wait at all -- a
        freshly loaded document that answers a different question than the one
        the caller was asking of the form that went. `root_now` keeps the frame
        whose answer is "unreadable"."""
        page = self.FakePage()
        replacement = self.FakeFrame("http://ha.test/api/hassio_ingress/tok/odoo",
                                     parent=page.main_frame)
        page._frames.append(replacement)
        held = self.FakeFrame("http://ha.test/api/hassio_ingress/tok/odoo",
                              parent=page.main_frame, detached=True)
        side = self.ingress_side(page, held=held)
        self.assertIs(side.root, replacement)
        self.assertIs(self.ingress_side(page, held=held).root_now, held)

    def test_a_side_nothing_has_run_through_yet_falls_back_to_the_search(self) -> None:
        """Holding no frame is not the path #288 is about: there the waiting
        resolve is the only resolve there is, and it is the right one -- the
        panel may still be loading."""
        page = self.FakePage()
        frame = self.FakeFrame("http://ha.test/api/hassio_ingress/tok/odoo", parent=page.main_frame)
        page._frames.append(frame)
        side = self.ingress_side(page, held=None)
        self.assertIs(side.root_now, frame)
        self.assertEqual(page.waits, 0)

    def test_the_base_class_resolve_is_the_very_same_root(self) -> None:
        """The default sits on `Side` so the four other Live drivers on this layer
        are provably untouched: on a surface whose root is the page itself the two
        properties are the same object, and `PublicSide` does not override either.
        """
        side = e2e_parity_shared_layers_live.PublicSide.__new__(
            e2e_parity_shared_layers_live.PublicSide)
        side.page = object()
        self.assertIs(side.root_now, side.root)
        self.assertIs(side.root_now, side.page)
        self.assertNotIn("root_now", vars(e2e_parity_shared_layers_live.PublicSide))

    def test_only_the_ingress_side_overrides_it(self) -> None:
        """`root`, its cache and `_find_frame`'s 60 s default are unchanged -- the
        other callers legitimately want a panel that is still loading -- so the
        one override is the whole of this change on the shared layer."""
        self.assertIn("root_now", vars(e2e_parity_shared_layers_live.IngressSide))
        self.assertIn("root_now", vars(e2e_parity_shared_layers_live.Side))
        self.assertEqual(
            e2e_parity_shared_layers_live.IngressSide._find_frame.__defaults__, (60,))


if __name__ == "__main__":
    unittest.main()
