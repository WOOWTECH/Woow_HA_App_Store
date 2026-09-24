#!/usr/bin/env python3
"""Pure logic of the Literal rewrite gate (issue #58, ADR 0004).

Under Ingress the Runtime shim prefixes every URL the browser uses through
an API it can intercept. The Literal rewrite, the nginx `sub_filter` rules in
the Ingress `location ^~ /web/assets/` block, exists only for what the shim
cannot reach: whole-page navigations and path comparisons written as string
literals inside asset bundles. This module decides, for the bundles a
deployment actually serves, whether any root-relative literal is used in one
of those contexts without a matching rule, and turns what it finds into the
Generated rewrites nginx includes from that block (`generate_include`, ADR
0005).

Everything here is a pure function over strings so the static tier can pin
the behaviour with fixtures. The module ships in the image next to the
maintenance library so the same code can serve inside the container and out:
`tests/e2e_literal_rewrite_gate.py` is the Live-tier CLI that logs in,
collects the bundles and calls these functions, and
`tests/test_literal_rewrite_gate.py` loads it by path, as the maintenance
bootstrap tests load theirs.

Levels, by how the bundle consumes the literal:

- ``FAIL``  whole-page navigation: ``location.href =``, ``location.pathname =``,
  ``location =``, ``location.assign(``, ``location.replace(``, Odoo ``redirect(``.
- ``WARN``  path comparison whose other side is the location: ``startsWith``,
  ``includes``, ``indexOf`` on ``pathname``/``location``/``href``, or
  ``===``/``!==`` against one of them.
- ``INFO``  everything else: RPC paths, script and image sources, template
  paths, CSS ``url(``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Iterable, Mapping

LEVELS = ("FAIL", "WARN", "INFO")
_RANK = {level: index for index, level in enumerate(LEVELS)}

#: Key under which `rewrite_rules` records the generic CSS ``url(/`` rules.
CSS_URL_RULE = "url("

# A root-relative literal: a quote (or CSS `url(` with an optional quote),
# then `/` and one path segment, then a separator that ends the segment.
_LITERAL = re.compile(
    r"""(?:url\((?P<css_quote>["']?)|(?P<quote>["'`]))"""
    r"""/(?P<segment>[A-Za-z0-9_.-]+)(?=(?P<after>[/"'`?#)])|$)"""
)

# Context windows: enough to see the call or comparison the literal sits in,
# small enough that an unrelated `location` two statements away is not seen.
_BEFORE = 120
_AFTER = 80

# Between the navigation operator and the literal, minified Odoo often puts
# a short expression: `location.href=url||"/odoo"`, `x?"/a":"/b"`,
# `base+"/x"`. The tail admits one such expression up to the operator that
# introduces the literal, and stops at a statement or call boundary.
_EXPRESSION_TAIL = r"(?:[^;{}()]{0,60}?(?:\|\||\?\?|\?|:|\+))?\s*"
_NAVIGATION_BEFORE = re.compile(
    r"(?:"
    r"(?<![\w$])location\s*(?:"
    r"(?:\.\s*(?:href|pathname))?\s*=(?!=)"                # location.href = "/x", location = "/x"
    r"|\.\s*(?:assign|replace)\s*\("                        # location.assign("/x")
    r")"
    r"|(?<![\w$])redirect\s*\("                             # redirect("/x")
    r")" + _EXPRESSION_TAIL + r"$"
)
# A path comparison is a WARN only when the other side of the comparison is
# the location: the receiver of `.startsWith(`, the other operand of `===`,
# or the argument of an array `.includes(`. An unrelated `location` in the
# same statement (`new URL(x, location.origin)`) does not count.
_OPERAND = r"[^;{}=!&|,()]{0,80}"
_METHOD_BEFORE = re.compile(
    r"(?P<partner>" + _OPERAND + r")\.\s*(?:startsWith|includes|indexOf|endsWith)\s*\(\s*$"
)
_EQUALITY_BEFORE = re.compile(r"(?P<partner>" + _OPERAND + r")\s*[!=]==?\s*$")
# The after-context starts just past the literal's closing quote.
_EQUALITY_AFTER = re.compile(r"^\s*[!=]==?\s*(?P<partner>" + _OPERAND + r")")
_ARRAY_INCLUDES_AFTER = re.compile(r"^[^\]]*\]\s*\.\s*includes\s*\(\s*(?P<partner>[^)]*)")
# How far a literal may run before we give up looking for its closing quote.
_MAX_LITERAL = 400
_LOCATION_PARTNER = re.compile(r"pathname|location|href")

_INGRESS_TOKEN = re.compile(r"(?P<prefix>/?api/hassio_ingress/)[^/\s?#<>\"']+")
_SNIPPET_RADIUS = 60


@dataclass(frozen=True)
class Finding:
    """One root-relative literal in a bundle and how the bundle uses it."""

    prefix: str
    level: str
    quote: str          # '"', "'", "`" or "" (unquoted CSS url)
    context: str        # "string" or "css_url"
    snippet: str

    @property
    def key(self) -> tuple[str, str]:
        """What an exception entry matches: the prefix at this level."""
        return (self.prefix, self.level)


def mask(text: str) -> str:
    """Redact the Ingress token wherever it appears, as the other Live tests do."""
    return _INGRESS_TOKEN.sub(lambda match: match.group("prefix") + "<redacted>", text)


def _snippet(text: str, start: int, end: int) -> str:
    lo = max(0, start - _SNIPPET_RADIUS)
    hi = min(len(text), end + _SNIPPET_RADIUS)
    return mask(text[lo:hi].replace("\n", " "))


def _level(text: str, start: int, end: int) -> str:
    before = text[max(0, start - _BEFORE):start]
    after = text[end:end + _AFTER]
    if _NAVIGATION_BEFORE.search(before):
        return "FAIL"
    for pattern, text_side in (
        (_METHOD_BEFORE, before),
        (_EQUALITY_BEFORE, before),
        (_EQUALITY_AFTER, after),
        (_ARRAY_INCLUDES_AFTER, after),
    ):
        match = pattern.search(text_side)
        if match and _LOCATION_PARTNER.search(match.group("partner")):
            return "WARN"
    return "INFO"


def scan_bundle(text: str) -> list[Finding]:
    """One pass over a bundle: every root-relative literal with its level."""
    findings: list[Finding] = []
    for match in _LITERAL.finditer(text):
        after = match.group("after") or ""
        prefix = "/" + match.group("segment") + ("/" if after == "/" else "")
        css = match.group("css_quote") is not None
        quote = match.group("css_quote") if css else match.group("quote")
        # The level is decided from the literal's opening quote to its closing
        # one, so the `url(` of a CSS literal counts as its own context, not
        # as a call, and a comparison after a long literal is still seen.
        literal_start = match.start("segment") - 1 - len(quote)
        closer = quote or ")"
        close_at = text.find(closer, match.end(), match.end() + _MAX_LITERAL)
        literal_end = close_at + 1 if close_at != -1 else match.end()
        findings.append(Finding(
            prefix=prefix,
            level=_level(text, literal_start, literal_end),
            quote=quote,
            context="css_url" if css else "string",
            snippet=_snippet(text, match.start(), match.end()),
        ))
    return findings


def extract_prefixes(text: str) -> Counter[str]:
    """Prefix -> number of root-relative literals using it."""
    return Counter(finding.prefix for finding in scan_bundle(text))


def classify(text: str, prefix: str) -> str:
    """The highest level any literal with `prefix` reaches in the bundle."""
    levels = [finding.level for finding in scan_bundle(text) if finding.prefix == prefix]
    if not levels:
        raise ValueError(f"{prefix} does not occur in the bundle")
    return min(levels, key=_RANK.__getitem__)


# --- nginx ----------------------------------------------------------------

_INGRESS_SERVER_MARKER = "# HA Supervisor Ingress adapter."
_ASSETS_LOCATION_MARKER = "location ^~ /web/assets/ {"
_SUB_FILTER = re.compile(r"""sub_filter\s+(?:'([^']*)'|"([^"]*)")\s+(?:'[^']*'|"[^"]*")\s*;""")
_PREFIX_RULE = re.compile(r"""^(?P<quote>["'`])(?P<prefix>/[A-Za-z0-9_.-]+/?)$""")
_CSS_URL_RULE = re.compile(r"""^url\((?P<quote>["']?)/$""")


def ingress_assets_block(template: str) -> str:
    """The text of the Ingress server's `location ^~ /web/assets/` block."""
    server = template.index(_INGRESS_SERVER_MARKER)
    start = template.index(_ASSETS_LOCATION_MARKER, server)
    # The block ends at the closing brace written at the same indentation as
    # its `location` line. Braces inside sub_filter strings never start a
    # line, so this holds however the template is re-indented.
    line_start = template.rfind("\n", 0, start) + 1
    indent = template[line_start:start]
    end = template.index("\n" + indent + "}", start + len(_ASSETS_LOCATION_MARKER))
    return template[start:end]


def _prefix_rules(text: str) -> dict[str, frozenset[str]]:
    """Prefix -> quote variants, from every `sub_filter` directive in `text`."""
    variants: dict[str, set[str]] = {}
    for match in _SUB_FILTER.finditer(text):
        source = match.group(1) if match.group(1) is not None else match.group(2)
        prefix_rule = _PREFIX_RULE.match(source)
        if prefix_rule:
            variants.setdefault(prefix_rule.group("prefix"), set()).add(prefix_rule.group("quote"))
            continue
        css_rule = _CSS_URL_RULE.match(source)
        if css_rule:
            variants.setdefault(CSS_URL_RULE, set()).add(css_rule.group("quote"))
    return {prefix: frozenset(quotes) for prefix, quotes in variants.items()}


def rewrite_rules(template: str) -> dict[str, frozenset[str]]:
    """Prefix -> quote variants the Literal rewrite substitutes it in.

    Only plain prefix rules (``'"/web/'``) and the generic CSS ``url(/`` rules
    are collected. Exact-expression patches (router, bus worker, settings
    icon) are not prefix rules and are ignored. The CSS rules are recorded
    under `CSS_URL_RULE` with the quote variants they cover.
    """
    return _prefix_rules(ingress_assets_block(template))


def include_rules(text: str) -> dict[str, frozenset[str]]:
    """The same mapping for a Generated rewrite include file.

    `generate_include` writes bare `sub_filter` lines with no enclosing
    `location` block, so the file is read directly instead of through
    `ingress_assets_block`. The rules mean what the Shipped ones mean: what
    the file holds is what nginx substitutes on that host.
    """
    return _prefix_rules(text)


def merge_rules(*rule_sets: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """The effective rules of several sources, quote variants unioned per prefix.

    A host that applied Generated rewrites substitutes the template's rules
    and the generated ones. Evaluating against the merge is what makes the
    gate report that host rather than the image: a prefix the host already
    covers is covered, not an unregistered FAIL reported a second time.
    """
    merged: dict[str, set[str]] = {}
    for rules in rule_sets:
        for prefix, quotes in rules.items():
            merged.setdefault(prefix, set()).update(quotes)
    return {prefix: frozenset(quotes) for prefix, quotes in merged.items()}


def rewrite_prefixes(template: str) -> set[str]:
    """The prefixes the Literal rewrite covers, as written in the template."""
    return {prefix for prefix in rewrite_rules(template) if prefix != CSS_URL_RULE}


def is_covered(finding: Finding, rules: Mapping[str, frozenset[str]]) -> bool:
    """Would nginx rewrite this literal as served? Quote variants matter."""
    if finding.context == "css_url" and finding.quote in rules.get(CSS_URL_RULE, ()):
        return True
    if finding.quote in rules.get(finding.prefix, ()):
        return True
    # A bare rule (`"/odoo`) also rewrites the slashed literal (`"/odoo/x`);
    # a slashed rule (`"/web/`) never rewrites the bare literal (`"/web"`).
    if finding.prefix.endswith("/") and finding.quote in rules.get(finding.prefix[:-1], ()):
        return True
    return False


#: Quote variants a Generated rewrite is written in, in the order the include
#: file lists them. The same three the hand-written prefix rules use.
GENERATED_QUOTES = ('"', "'", "`")


def _shipped_covers(prefix: str, rules: Mapping[str, frozenset[str]]) -> bool:
    """Does a Shipped rewrite already touch this prefix, in any quote variant?

    Coarser than `is_covered`, which answers for one literal and the quote it
    is written in. A Generated rewrite is emitted in all three variants at
    once, so a prefix the template rewrites at all is left to the Shipped
    rewrite rather than half-duplicated in the generated file.

    The cost is a prefix the template rewrites in some variants but not all:
    `/report/` ships in the `"` variant only, so a navigation written
    `location.href='/report/x'` earns no Generated rewrite. The gate keeps
    reporting it as an unregistered FAIL, and the fix is the missing Shipped
    variant in the template, not a second rule for the same prefix here.
    """
    if prefix in rules:
        return True
    # A bare rule (`"/odoo`) already rewrites the slashed literal, the same
    # direction `is_covered` allows; a slashed rule never covers the bare one.
    return prefix.endswith("/") and prefix[:-1] in rules


def generate_include(
    findings: Iterable[Finding],
    shipped_rules: Mapping[str, frozenset[str]],
    exceptions: Iterable[tuple[str, str]],
) -> str:
    """The text of the nginx `include` file holding the Generated rewrites.

    A prefix earns rules only when a bundle uses it in a whole-page navigation
    (`FAIL`), no Shipped rewrite covers it, and it is not registered in the
    exception list. Path comparisons (`WARN`) and everything the Runtime shim
    intercepts (`INFO`) never do, per ADR 0004.

    Pure and byte-stable: the same findings in any order, with repeats,
    produce the same bytes, so a rescan that found nothing new writes nothing
    new and nginx is not reloaded for an unchanged file.
    """
    excepted = set(exceptions)
    prefixes = {
        finding.prefix
        for finding in findings
        if finding.level == "FAIL"
        and finding.key not in excepted
        and not _shipped_covers(finding.prefix, shipped_rules)
    }
    lines: list[str] = []
    for prefix in sorted(prefixes):
        for quote in GENERATED_QUOTES:
            # nginx quotes a directive argument with either quote character;
            # use the one the argument itself does not contain.
            outer = '"' if quote == "'" else "'"
            lines.append(
                f"sub_filter {outer}{quote}{prefix}{outer}"
                f" {outer}{quote}$safe_ingress_path{prefix}{outer};\n"
            )
    return "".join(lines)


# --- exceptions -----------------------------------------------------------

def load_exceptions(text: str) -> set[tuple[str, str]]:
    """Parse the checked-in exception list: prefix, level and a reason each.

    PyYAML is imported here rather than at the top of the module because
    nothing installs it in the image: it is a test requirement only
    (`release.yml:85`, `tests/requirements-test.txt:4`). The first caller
    inside the container, `odoo-rewrite-scan` (issue #92), needs `mask()`
    and the classification, not this function, and used to fail on the
    import alone.

    A later in-container caller does need the list -- ADR 0005 keeps the
    shipped exceptions applying to Generated rewrites -- and will have to
    put PyYAML in the image or read the list another way. Keeping the
    import here is what leaves that a choice rather than a start-up
    failure for everything that imports this module.
    """
    import yaml

    entries = yaml.safe_load(text) or []
    if not isinstance(entries, list):
        raise ValueError("the exception list must be a YAML sequence of entries")
    exceptions: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"exception {index}: expected a mapping with prefix, level and reason")
        prefix, level, reason = entry.get("prefix"), entry.get("level"), entry.get("reason")
        if not isinstance(prefix, str) or not prefix.startswith("/"):
            raise ValueError(f"exception {index}: prefix must be a root-relative path, got {prefix!r}")
        if level not in LEVELS:
            raise ValueError(f"exception {index}: level must be one of {', '.join(LEVELS)}, got {level!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"exception {index} ({prefix} {level}): a reason is required")
        exceptions.add((prefix, level))
    return exceptions


# --- evaluation -----------------------------------------------------------

@dataclass
class BundleReport:
    name: str
    size: int
    findings: list[Finding] = field(default_factory=list)          # uncovered only
    exception_hits: list[Finding] = field(default_factory=list)    # one per (prefix, level)
    unregistered_failures: list[Finding] = field(default_factory=list)

    @property
    def levels(self) -> dict[str, str]:
        """Uncovered prefix -> its highest level (exception hits included)."""
        levels: dict[str, str] = {}
        for finding in self.findings:
            current = levels.get(finding.prefix)
            if current is None or _RANK[finding.level] < _RANK[current]:
                levels[finding.prefix] = finding.level
        return levels

    def counts(self, level: str) -> Counter[str]:
        return Counter(f.prefix for f in self.findings if f.level == level)


@dataclass
class GateReport:
    bundles: dict[str, BundleReport]
    rules: Mapping[str, frozenset[str]]
    exceptions: set[tuple[str, str]]

    @property
    def exit_code(self) -> int:
        return 1 if any(b.unregistered_failures for b in self.bundles.values()) else 0


def evaluate_findings(
    bundles: Mapping[str, tuple[int, Iterable[Finding]]],
    rules: Mapping[str, frozenset[str]],
    exceptions: Iterable[tuple[str, str]],
) -> GateReport:
    """Drop covered literals, apply exceptions, decide — over findings already taken.

    Split out of `evaluate` for the caller that has scanned the bundles
    itself and must not scan them twice. Inside the container both halves
    of a round want the same findings: `generate_include` selects the rules
    from them and the add-on log summarises them (`rewrite_apply`, issue
    #94). A second `scan_bundle` pass over every bundle would double the
    four seconds of analysis a round costs, which is the cost ADR 0007
    measured and the whole reason a scan keeps a state at all.

    Each bundle is given as `(size in bytes, its findings)`, because a
    report prints the size and the findings no longer carry the text.
    """
    exceptions = set(exceptions)
    report = GateReport(bundles={}, rules=rules, exceptions=exceptions)
    for name, (size, findings) in bundles.items():
        bundle = BundleReport(name=name, size=size)
        seen_hits: set[tuple[str, str]] = set()
        for finding in findings:
            if is_covered(finding, rules):
                continue
            bundle.findings.append(finding)
            if finding.key in exceptions:
                if finding.key not in seen_hits:
                    seen_hits.add(finding.key)
                    bundle.exception_hits.append(finding)
            elif finding.level == "FAIL":
                bundle.unregistered_failures.append(finding)
        report.bundles[name] = bundle
    return report


def evaluate(
    bundles: Mapping[str, str],
    rules: Mapping[str, frozenset[str]],
    exceptions: Iterable[tuple[str, str]],
) -> GateReport:
    """Scan every bundle, drop covered literals, apply exceptions, decide."""
    return evaluate_findings(
        {name: (len(text), scan_bundle(text)) for name, text in bundles.items()},
        rules,
        exceptions,
    )


def format_report(report: GateReport, header: Iterable[str] = ()) -> str:
    """Human-readable result, one block per bundle, Ingress tokens masked."""
    lines: list[str] = ["Literal rewrite gate", *header]
    prefixes = sorted(p for p in report.rules if p != CSS_URL_RULE)
    lines.append(f"rules: {len(prefixes)} prefixes in the Ingress asset location: {' '.join(prefixes)}")
    lines.append(f"exceptions: {len(report.exceptions)} registered")
    lines.append(f"bundles: {len(report.bundles)}")

    # The summary counts (bundle, prefix) pairs at each level, exceptions
    # excluded, the same unit as the rows printed per bundle.
    total_fail = total_warn = 0
    info_prefixes: set[str] = set()
    for bundle in report.bundles.values():
        lines.append("")
        lines.append(f"== {bundle.name} ({bundle.size} bytes)")
        excepted = {f.key for f in bundle.exception_hits}
        for level in ("FAIL", "WARN"):
            counts = bundle.counts(level)
            shown: set[str] = set()
            for finding in bundle.findings:
                if finding.level != level or finding.prefix in shown:
                    continue
                shown.add(finding.prefix)
                tag = "exception" if finding.key in excepted else level
                lines.append(f"  {tag:<9} {finding.prefix:<20} x{counts[finding.prefix]:<4} {finding.snippet}")
            unexcused = sum(1 for p in counts if (p, level) not in excepted)
            if level == "FAIL":
                total_fail += unexcused
            else:
                total_warn += unexcused
        info = bundle.counts("INFO")
        if info:
            info_prefixes.update(info)
            listed = ", ".join(f"{prefix} x{count}" for prefix, count in sorted(info.items()))
            lines.append(f"  INFO      {listed}")
        if not bundle.findings:
            lines.append("  (every root-relative literal is covered)")

    lines.append("")
    hits = sorted({(f.prefix, f.level) for b in report.bundles.values() for f in b.exception_hits})
    lines.append(
        f"summary: unregistered FAIL {total_fail}, WARN {total_warn}, "
        f"INFO prefixes {len(info_prefixes)}, exception hits {len(hits)}"
        + (": " + ", ".join(f"{p} {l}" for p, l in hits) if hits else "")
    )
    lines.append("result: " + ("FAIL" if report.exit_code else "pass"))
    return mask("\n".join(lines))
