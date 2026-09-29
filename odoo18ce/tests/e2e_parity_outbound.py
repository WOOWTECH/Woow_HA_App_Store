#!/usr/bin/env python3
"""Outbound-artefact parity run: group E and U-D8 of the parity plan (#145).

Group E is what the server builds for the outside world: links in outgoing
mail (`U-E2`), share dialogs (`U-E3`), report PDFs and their QR codes
(`U-E4`), absolute attachment URLs (`U-E5`) and exported files (`U-E7`);
`U-D8` adds the SEO outputs. Each artefact is produced once from the
Public origin and once under Ingress, and every URL
in it is classified against the **Canonical URL**.

Unlike groups F-D, the verdict is not only a comparison of the two
surfaces: the same Ingress token in both copies of a mail is still a leak.
A record is `PARITY` only when both results match, neither side raised a
signal, and neither artefact holds a URL on Home Assistant, a relative URL
or an Ingress token.

Where the shared object allows anonymous access, its link is also opened
from a browser with no session; a browser off the LAN adds its result
through `merge_off_lan`.

The pure parts are tested in the static tier by test_e2e_parity_outbound.py;
the Live part is in e2e_parity_outbound_live.py.
"""
from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.utils import getaddresses
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from e2e_menu_action_adapter import RunInfo
from e2e_parity_shared_layers import NOT_RUN, Outcome, check_identity, check_record, judge

OUTBOUND_SCREENS: tuple[tuple[str, str, str], ...] = (
    ("U-E2", "portal", "portal invitation"),
    ("U-E2", "auth_signup", "password reset"),
    ("U-E2", "mail", "chatter notification"),
    ("U-E2", "mass_mailing", "tracking and unsubscribe"),
    ("U-E2", "hr_holidays", "time off approval"),
    ("U-E2", "hr_expense", "expense approval"),
    # Every Share dialog on odoo_parity (share wizards and the actions bound
    # to them, 2026-09-25), plus the other link fields made to be handed out.
    ("U-E3", "sale_management", "quotation Share"),
    ("U-E3", "account", "invoice Share"),
    ("U-E3", "purchase", "purchase order Share"),
    ("U-E3", "project", "task Share"),
    ("U-E3", "project", "project Share"),
    ("U-E3", "survey", "survey Share"),
    ("U-E3", "spreadsheet_dashboard", "dashboard Share"),
    ("U-E3", "mail", "Discuss channel invitation"),
    ("U-E3", "im_livechat", "live chat channel links"),
    ("U-E3", "calendar", "meeting link"),
    ("U-E4", "account", "invoice PDF"),
    ("U-E4", "account", "invoice PDF without Payment"),
    ("U-E4", "event", "event ticket PDF"),
    ("U-E5", "mail", "attachment links in outgoing mail"),
    ("U-E7", "mass_mailing", "link tracker export xlsx"),
    ("U-E7", "mass_mailing", "link tracker export csv"),
    ("U-E7", "calendar", "meeting export xlsx"),
    ("U-E7", "calendar", "meeting export csv"),
    ("U-D8", "shared", "generic"),
    ("U-D8", "website", "sitemap.xml"),
)


def outbound_plan() -> list[tuple[str, str, str]]:
    return list(OUTBOUND_SCREENS)


# --- Classifying URLs -----------------------------------------------------------


@dataclass(frozen=True)
class Bases:
    """The Canonical URL, every Home Assistant entrance, and the Ingress prefix."""

    public: str
    ha: Sequence[str] = ()
    prefix: str | None = None


# XML namespace URIs are names, not links.
NAMESPACE_HOSTS = ("www.sitemaps.org", "www.w3.org", "www.google.com", "schemas.openxmlformats.org",
                   "schemas.microsoft.com", "purl.org", "schema.org")
_NOT_LINKS = ("mailto:", "tel:", "data:", "javascript:", "cid:", "#")
# Problems, the worst first: a token is a credential, the others a broken link.
PROBLEM_KINDS = ("ingress-token", "ha", "relative")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    port = parts.port
    default = {"http": 80, "https": 443}.get(parts.scheme)
    host = (parts.hostname or "").lower()
    return "%s://%s%s" % (parts.scheme.lower(), host, "" if port in (None, default) else ":%d" % port)


def classify_url(url: str, bases: Bases) -> str:
    url = url.strip()
    if not url or url.lower().startswith(_NOT_LINKS):
        return "not-a-link"
    if "/api/hassio_ingress/" in url or (bases.prefix and bases.prefix in url):
        return "ingress-token"
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        return "relative"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "not-a-link"
    if (parts.hostname or "").lower() in NAMESPACE_HOSTS:
        return "namespace"
    origin = _origin(url)
    if origin == _origin(bases.public):
        return "canonical"
    if origin in {_origin(base) for base in bases.ha}:
        return "ha"
    return "external"


def literal_findings(urls: Iterable[str], bases: Bases, *, allow_empty: bool = False) -> dict[str, Any]:
    """Counts per kind, and the URLs that are off the Canonical URL (as `url_shape`s: no token survives)."""
    counts: dict[str, int] = {}
    problems: list[str] = []
    for url in urls:
        kind = classify_url(url, bases)
        if kind in ("not-a-link", "namespace"):
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if kind in PROBLEM_KINDS:
            problems.append(url_shape(url))
    return {"ok": not problems and (allow_empty or bool(counts)), "counts": counts, "problems": problems}


def _segment_shape(segment: str, previous: str = "") -> str:
    if segment.isdigit():
        return "<id>"
    if previous == "r" and segment:  # a link tracker's short code
        return "<token>"
    stem = segment.rsplit(".", 1)[0] if re.search(r"\.(js|css|png|gif|jpg|svg|xml|txt|ico)$", segment) else segment
    if re.fullmatch(r"[a-z]+(?:[_-][a-z]+)*", stem):  # a route word such as unsubscribe_from_list
        return segment
    if len(stem) >= 16 or (re.search(r"\d", stem) and re.search(r"[A-Za-z]", stem)):
        return "<token>"
    return segment


def url_shape(url: str) -> str:
    """A URL for the evidence: its origin and path, ids and tokens replaced, no query."""
    parts = urlsplit(url)
    origin = "%s://%s" % (parts.scheme, parts.netloc) if parts.netloc else ""
    segments = parts.path.split("/")
    return origin + "/".join(_segment_shape(segment, segments[index - 1] if index else "")
                             for index, segment in enumerate(segments))


# --- Extracting URLs ------------------------------------------------------------

_ATTR = re.compile(r"""(?:href|src|action|content)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_BARE = re.compile(r"""https?://[^\s"'<>()\[\]]+""")


def extract_urls(text: str) -> list[str]:
    """Absolute and root-relative URLs in HTML or plain text, sorted and unique."""
    text = html.unescape(text)
    found = set()
    for match in _ATTR.findall(text):
        match = match.strip()
        if match.startswith(("http://", "https://", "//")) or (match.startswith("/") and len(match) > 1):
            found.add(match)
    for match in _BARE.findall(text):
        found.add(match.rstrip(".,;:!?"))
    return sorted(url for url in found if not url.lower().startswith(_NOT_LINKS))


def mail_urls(raw: bytes) -> dict[str, Any]:
    """Subject, recipients and every URL of one captured message (all text parts)."""
    message = message_from_bytes(raw, policy=policy.default)
    recipients = [str(value) for value in message.get_all("X-Capture-Rcpt", [])]
    if not recipients:
        recipients = [address for _, address in getaddresses([str(v) for v in message.get_all("To", [])])]
    urls: set[str] = set()
    for part in message.walk():
        if part.get_content_maintype() == "text":
            urls.update(extract_urls(part.get_content()))
    return {"subject": str(message.get("Subject", "")), "to": recipients, "urls": sorted(urls)}


_XLSX_TEXT = re.compile(r"<t(?:\s[^>]*)?>(.*?)</t>", re.DOTALL)


def xlsx_strings(data: bytes) -> list[str]:
    """Every string of an xlsx: shared strings first, then inline ones per sheet."""
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        parts = [name for name in names if name == "xl/sharedStrings.xml"]
        parts += sorted(name for name in names if name.startswith("xl/worksheets/") and name.endswith(".xml"))
        for name in parts:
            out.extend(html.unescape(text) for text in _XLSX_TEXT.findall(archive.read(name).decode("utf-8")))
    return out


def csv_strings(data: bytes) -> list[str]:
    return [cell for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))) for cell in row]


def qr_findings(payloads: Sequence[str], pdf_links: Sequence[str], bases: Bases) -> dict[str, Any]:
    """U-E4: the PDF must hold a QR code, and no URL in it or its links may be off the Canonical URL."""
    qr_urls = [url for payload in payloads for url in extract_urls(payload)]
    literal = literal_findings([*qr_urls, *pdf_links], bases, allow_empty=True)
    return {"ok": bool(payloads) and literal["ok"], "qr": {"count": len(payloads), "urls": len(qr_urls)},
            "literal": literal}


# --- Records --------------------------------------------------------------------


def _details_of(outcome: Outcome) -> Mapping[str, Any]:
    return outcome.details or {}


def outbound_record(run: RunInfo, item: str, module: str, screen: str, public: Outcome, ingress: Outcome, *,
                    bases: Bases, blocked_by: str | None = None, **kwargs) -> dict[str, Any]:
    """One group-E check: a comparison of the surfaces, plus absolute rules for each artefact.

    - a URL off the Canonical URL is a GAP (Blocker with an Ingress token), even on both surfaces;
    - an anonymous link (`details["reach"]`) that does not show its record is an Important GAP;
    - an artefact with nothing to judge (`literal["ok"]` false without a problem: no link, no QR code)
      cannot pass, so the check is NOT-RUN and must say what blocks it.
    """
    verdict, severity, reasons = judge(public, ingress)
    empty = False
    for name, outcome in (("public", public), ("ingress", ingress)):
        literal = _details_of(outcome).get("literal") or {}
        for url in literal.get("problems", []):
            kind = classify_url(url, bases)
            reasons.append("%s literal: %s %s" % (name, kind, url_shape(url)))
            verdict = "GAP"
            if kind == "ingress-token":
                severity = "blocker"
            elif severity == "none":
                severity = "important"
        for reached in _details_of(outcome).get("reach", []):
            if not reached["shown"]:
                reasons.append("%s anonymous: %s not shown (HTTP %s)" % (name, reached["link"], reached["status"]))
                verdict = "GAP"
                severity = "important" if severity == "none" else severity
        empty = empty or (outcome.available and literal and not literal.get("ok") and not literal.get("problems"))
    notes = "; ".join(filter(None, [kwargs.pop("notes", ""), *reasons]))
    if verdict == "PARITY" and empty:
        if not blocked_by:
            raise ValueError("%s %s: the artefact holds nothing to judge; name what blocks the check" % (item, screen))
        return check_record(run, item, module=module, screen=screen, public=public, ingress=ingress,
                            verdict=NOT_RUN, blocked_by=blocked_by, notes=notes, **kwargs)
    return check_record(run, item, module=module, screen=screen, public=public, ingress=ingress,
                        verdict=verdict, severity=severity, notes=notes, **kwargs)


def merge_off_lan(records: Iterable[Mapping[str, Any]], results: Iterable[Mapping[str, Any]], *,
                  browser: str) -> list[dict[str, Any]]:
    """Add what an off-LAN browser saw for each anonymous link (`link` is its `url_shape`);
    a link that does not show its record turns the check into an Important GAP.

    The results for a side replace what an earlier merge recorded for it."""
    records = [dict(record) for record in records]
    by_identity = {record["control_identity"]: record for record in records}
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for result in results:
        if result["identity"] not in by_identity:
            raise ValueError("no record for %s" % result["identity"])
        grouped.setdefault((result["identity"], result["side"]), []).append(result)
    for (identity, side), side_results in grouped.items():
        record = by_identity[identity]
        block = dict(record[side])
        block["details"] = dict(block.get("details") or {})
        block["details"]["off_lan"] = {"browser": browser, "links": [
            {"link": result.get("link"), "status": result["status"], "shown": bool(result["shown"])}
            for result in side_results]}
        record[side] = block
        for result in side_results:
            if result["shown"]:
                continue
            note = "%s off-LAN: %s not shown (HTTP %s)" % (side, result.get("link") or "link", result["status"])
            if note not in (record.get("notes") or ""):
                record["notes"] = "; ".join(filter(None, [record.get("notes"), note]))
            if record["verdict"] == "PARITY":
                record["verdict"], record["severity"] = "GAP", "important"
    return records


__all__ = [
    "Bases", "OUTBOUND_SCREENS", "check_identity", "classify_url", "csv_strings", "extract_urls",
    "literal_findings", "mail_urls", "merge_off_lan", "outbound_plan", "outbound_record", "qr_findings",
    "url_shape", "xlsx_strings",
]
