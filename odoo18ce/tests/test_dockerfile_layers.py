#!/usr/bin/env python3
"""Static-tier guard for the image's layer layout (issue #154, ADR 0013).

One `RUN` used to install PostgreSQL, the Odoo nightly `.deb` and every
small addition together, and it produced one ~690 MiB compressed layer.
Adding `python3-yaml`, then `python3-pycryptodome`, changed that layer, so
every host downloaded all of it again -- and on a slow link the Supervisor's
pull never converged, because Docker cannot resume a partial layer
(issue #153). The Dockerfile now builds three layers instead:

* **(a)** the stable packages, including the pinned `.deb`'s own `Depends`
* **(b)** the Odoo `.deb` alone, with the two `ODOO_DEB_*` ARGs declared
  directly above it, below (a), so a bump misses only (b)'s cache
* **(c)** small apt additions, which is where a new package goes

This module freezes that order as text, the way the other Dockerfile and
workflow tests read their files -- no Dockerfile-parser dependency. It also
self-tests: seven mutations of the Dockerfile that must turn it red, and a
bot-style rewrite of the four pinned values that must leave it green --
including the weekly odoo-bump, which must reach the image build that
proves the new package.
"""
import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DEPENDS = ROOT / "odoo-deb-depends.txt"
ADR_DIR = ROOT.parent / "docs/adr"

# The ARG values a bump rewrites. They are replaced by placeholders before
# the sequence is compared, so the weekly odoo-bump and a LAYER_A_REFRESH
# never touch this test.
PINNED_ARGS = ("BASE_IMAGE_TAG", "ODOO_DEB_VERSION", "ODOO_DEB_SHA256",
               "LAYER_A_REFRESH")

# The packages layer (a) installs that are the add-on's own, not the Odoo
# `.deb`'s `Depends`. Everything else in (a) comes from odoo-deb-depends.txt.
LAYER_A_OWN = {
    "fonts-noto-cjk",
    "git",
    "jq",
    "nginx",
    "postgresql-16",
    "postgresql-client-16",
    "wkhtmltopdf",
}

# What a layer costs a user who has to download it again. Measured on amd64
# as `.deb` download sizes for 0.4.4 (issue #154): 207 MiB of stable
# packages plus 271 MiB of Odoo dependencies in (a), and the 235 MiB `.deb`
# in (b).
SIZES = {
    "(a)": "layer (a), the stable packages, about 480 MiB",
    "(b)": "layer (b), the Odoo package, about 235 MiB",
    "(c)": "layer (c), the small additions, a few MiB",
}

HOW_TO_CHANGE = (
    "Every user of the add-on downloads that layer again when it changes, "
    "and on a slow link the Supervisor's pull may never finish (#153). A "
    "small apt addition belongs in layer (c), which is cheap to re-send "
    "(ADR 0013). If the change above is intended, edit EXPECTED_SEQUENCE in "
    "this file to match and note the new download in the CHANGELOG."
)

DEB_URL = 'odoo_${ODOO_DEB_VERSION}_all.deb'

# The normalized instruction sequence from FROM through layer (b), frozen.
EXPECTED_SEQUENCE = [
    'FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:${BASE_IMAGE_TAG}',
    'SHELL ["/bin/bash", "-o", "pipefail", "-c"]',
    (
        'RUN apt-get update && apt-get install -y --no-install-recommends '
        'gnupg2 curl ca-certificates && echo "deb '
        'http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > '
        '/etc/apt/sources.list.d/pgdg.list && curl -fsSL '
        'https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor '
        '-o /etc/apt/trusted.gpg.d/postgresql.gpg && rm -rf '
        '/var/lib/apt/lists/*'
    ),
    'ARG LAYER_A_REFRESH="<LAYER_A_REFRESH>"',
    (
        'RUN echo "layer (a) refreshed ${LAYER_A_REFRESH}" && apt-get update '
        '&& apt-get install -y --no-install-recommends adduser fonts-dejavu-'
        'core fonts-font-awesome fonts-inconsolata fonts-noto-cjk fonts-'
        'roboto-unhinted git gsfonts jq libjs-underscore lsb-base nginx '
        'postgresql-16 postgresql-client-16 python3 python3-asn1crypto '
        'python3-babel python3-cbor2 python3-chardet python3-cryptography '
        'python3-dateutil python3-decorator python3-docutils '
        'python3-freezegun python3-geoip2 python3-gevent python3-greenlet '
        'python3-idna python3-jinja2 python3-libsass python3-lxml '
        'python3-markupsafe python3-num2words python3-ofxparse '
        'python3-openpyxl python3-openssl python3-passlib python3-pil '
        'python3-polib python3-psutil python3-psycopg2 python3-pypdf2 '
        'python3-qrcode python3-renderpm python3-reportlab python3-requests '
        'python3-rjsmin python3-serial python3-stdnum python3-tz '
        'python3-urllib3 python3-usb python3-vobject python3-werkzeug '
        'python3-xlrd python3-xlsxwriter python3-xlwt python3-zeep '
        'wkhtmltopdf && apt-get clean && rm -rf /var/lib/apt/lists/*'
    ),
    'ARG ODOO_DEB_VERSION="<ODOO_DEB_VERSION>"',
    'ARG ODOO_DEB_SHA256="<ODOO_DEB_SHA256>"',
    (
        'RUN apt-get update && curl -fsSL '
        '"https://nightly.odoo.com/18.0/nightly/deb/odoo_${ODOO_DEB_VERSION}_all.deb"'
        ' -o /tmp/odoo.deb && echo "${ODOO_DEB_SHA256} /tmp/odoo.deb" | '
        'sha256sum -c - && apt-get install -y --no-install-recommends '
        '/tmp/odoo.deb && apt-get clean && rm -rf /var/lib/apt/lists/* '
        '/tmp/odoo.deb'
    ),
]


# ── reading the Dockerfile as text ─────────────────────────────────────


def instructions(text: str) -> list[str]:
    """The Dockerfile's instructions, normalized.

    Backslash continuations joined, comment lines dropped, whitespace
    collapsed, and the four pinned ARG values replaced by placeholders.
    """
    joined: list[str] = []
    buf = ""
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        buf += line
        if buf.strip():
            joined.append(" ".join(buf.split()))
        buf = ""
    if buf.strip():
        joined.append(" ".join(buf.split()))
    out = []
    for one in joined:
        for name in PINNED_ARGS:
            one = re.sub(r'^ARG %s="[^"]*"$' % name,
                         'ARG %s="<%s>"' % (name, name), one)
        out.append(one)
    return out


def apt_packages(run: str) -> list[str]:
    """The package names one normalized apt `RUN` installs, flags dropped.

    Every `apt-get install` in the RUN, not only the first: a RUN that
    installs twice must not be able to hide a second `postgresql-16` from
    the "exactly one RUN" check.
    """
    words: list[str] = []
    for found in re.finditer(r"apt-get install (.*?)(?: &&|$)", run):
        words += [word for word in found.group(1).split()
                  if not word.startswith("-")]
    return words


# A note is `<kind>: <value>`, and several are separated by `; `. `deferred`
# and `dropped` are the two that keep layer (a) frozen across an Odoo bump:
# `deferred` is in the .deb's Depends and not installed by (a) yet, and
# `dropped` is no longer in Depends and still installed by (a). Both wait
# for an event that rebuilds (a) anyway (ADR 0013).
NOTE_KINDS = {"alternatives", "version", "qualifier", "satisfied-by",
              "deferred", "dropped"}


def read_depends(text: str) -> list[tuple[str, dict[str, str]]]:
    """odoo-deb-depends.txt as (package name, notes) pairs, in file order."""
    entries = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, _, raw_notes = line.partition("  # ")
        notes: dict[str, str] = {}
        kind = None
        for part in raw_notes.split("; "):
            # A fragment opens a note when it starts with a kind, whether or
            # not the kind is documented -- a typo must be reported and not
            # swallowed as prose. Anything else continues the note before
            # it, because a reason may contain a semicolon.
            opener = re.match(r"([a-z][a-z0-9-]*):\s*(.*)$", part)
            if opener:
                kind = opener.group(1)
                notes[kind] = opener.group(2).strip()
            elif kind is not None:
                notes[kind] = (notes[kind] + "; " + part).strip()
            elif part.strip():
                notes[part.strip()] = ""
        entries.append((name.strip(), notes))
    return entries


# ── the guard itself ───────────────────────────────────────────────────


def _runs_installing(instrs: list[str], package: str) -> list[int]:
    """The RUNs that install exactly this package. A whole word: layer (c)
    may add `postgresql-16-pgvector` without making (a) ambiguous."""
    return [i for i, one in enumerate(instrs)
            if one.startswith("RUN ") and package in apt_packages(one)]


def _runs_containing(instrs: list[str], needle: str) -> list[int]:
    return [i for i, one in enumerate(instrs)
            if one.startswith("RUN ") and needle in one]


def _which_layer(sequence: list[str], upto: int) -> str:
    """The costliest layer a change at `upto` re-sends: itself, or the first
    one under it."""
    for one in sequence[upto:]:
        if "postgresql-16" in apt_packages(one):
            return SIZES["(a)"]
        if DEB_URL in one:
            return SIZES["(b)"]
    return SIZES["(c)"]


def guard_failures(dockerfile: str, depends: str) -> list[str]:
    """Every way the layout is wrong, as readable messages. Empty is good."""
    problems = []
    instrs = instructions(dockerfile)

    # Each layer is found by content, not by position, and each must be
    # exactly one RUN.
    a = _runs_installing(instrs, "postgresql-16")
    b = _runs_containing(instrs, DEB_URL)
    for label, hits, what in (("(a)", a, "installing postgresql-16"),
                              ("(b)", b, "downloading the Odoo .deb")):
        if len(hits) != 1:
            problems.append(
                "layer %s must be exactly one RUN %s; found %d. %s"
                % (label, what, len(hits), HOW_TO_CHANGE))
    if not a or not b:
        return problems

    # (c) is the next apt-get install RUN after (b).
    after = [i for i, one in enumerate(instrs)
             if i > b[0] and one.startswith("RUN ") and "apt-get install" in one]
    if not after:
        problems.append(
            "layer (c) is gone: there is no apt-get install RUN after layer "
            "(b). ADR 0013 allows folding (c) into (a) or (b), but only "
            "together with an event that rebuilds them anyway. If that is "
            "what happened, drop this check with the same edit that updates "
            "EXPECTED_SEQUENCE, and note the full download in the CHANGELOG.")
        c = None
    else:
        c = after[0]

    # The frozen sequence, FROM through (b).
    start = next((i for i, one in enumerate(instrs)
                  if one.startswith("FROM ")), None)
    if start is None:
        problems.append("the Dockerfile has no FROM instruction")
    else:
        actual = instrs[start:b[0] + 1]
        if actual != EXPECTED_SEQUENCE:
            first = next((i for i in range(max(len(actual),
                                               len(EXPECTED_SEQUENCE)))
                          if actual[i:i + 1] != EXPECTED_SEQUENCE[i:i + 1]), 0)
            diff = "\n".join(difflib.unified_diff(
                EXPECTED_SEQUENCE, actual,
                fromfile="expected", tofile="Dockerfile", lineterm=""))
            problems.append(
                "the frozen instruction order changed; the first change "
                "re-sends %s.\n%s\n\n%s"
                % (_which_layer(EXPECTED_SEQUENCE, first), diff, HOW_TO_CHANGE))

    # (a) installs exactly the add-on's own packages plus the .deb's Depends.
    installed = apt_packages(instrs[a[0]])
    duplicates = sorted({p for p in installed if installed.count(p) > 1})
    if duplicates:
        problems.append("layer (a) lists these packages twice: %s" % duplicates)
    entries = read_depends(depends)
    names = [name for name, _ in entries]
    if names != sorted(names):
        problems.append(
            "odoo-deb-depends.txt is not sorted; the bot writes it sorted "
            "with LC_ALL=C")
    if len(set(names)) != len(names):
        problems.append("odoo-deb-depends.txt names a package twice")
    for name, notes in entries:
        unknown = sorted(set(notes) - NOTE_KINDS)
        if unknown:
            problems.append(
                "odoo-deb-depends.txt: %s carries a note this file does not "
                "document: %s" % (name, unknown))
    for name, notes in entries:
        for kind in ("deferred", "dropped"):
            if kind in notes and not notes[kind]:
                problems.append(
                    "odoo-deb-depends.txt: %s is marked %s without saying "
                    "why or until when" % (name, kind))
        if "deferred" in notes and "dropped" in notes:
            problems.append(
                "odoo-deb-depends.txt: %s cannot be both deferred and "
                "dropped" % name)
    # A `deferred` line is recorded but not installed in (a): apt pulls it
    # into (b) instead. A `dropped` one is the mirror -- gone from the
    # .deb's Depends, still in (a). Either way a nightly whose Depends
    # moved stays a 235 MiB bump rather than a 480 MiB one (ADR 0013).
    wanted = LAYER_A_OWN | {notes.get("satisfied-by") or name
                            for name, notes in entries
                            if "deferred" not in notes}
    if set(installed) != wanted:
        extra = sorted(set(installed) - wanted)
        missing = sorted(wanted - set(installed))
        problems.append(
            "layer (a) and odoo-deb-depends.txt disagree: (a) installs %s "
            "that the list does not ask for, and is missing %s. A package "
            "the add-on needs for itself belongs in LAYER_A_OWN in this "
            "file, not in odoo-deb-depends.txt, which records only what the "
            "pinned .deb depends on. %s"
            % (extra or "nothing", missing or "nothing", HOW_TO_CHANGE))

    # (c) comes after (b) and before the clone and the rootfs overlay.
    # The rootfs changes on nearly every Release; keeping it and the two
    # steps beside it below (c) is what lets an ordinary Release re-send
    # them alone and never re-run apt.
    # Every apt RUN after (b), not just the first: a fourth one added below
    # the overlay would be as wrong as (c) itself sitting there.
    if c is not None:
        clone = next((i for i, one in enumerate(instrs)
                      if one.startswith("RUN ") and "woow-addons" in one), None)
        overlay = next((i for i, one in enumerate(instrs)
                        if one.startswith("COPY rootfs/")), None)
        for label, where in (("the woow-addons clone", clone),
                             ("the rootfs COPY", overlay)):
            if where is None:
                problems.append("%s is gone from the Dockerfile" % label)
                continue
            for i in sorted(one for one in after if one > where):
                problems.append(
                    "%s must come before %s: a Release that changes only "
                    "what is below (c) must not re-run apt. %s"
                    % ("layer (c)" if i == c else "the apt RUN after (c)",
                       label, HOW_TO_CHANGE))

    # Nothing whose value changes on every build may sit above the last RUN:
    # it would miss the cache of every layer under it. ARG BUILD_ARCH above
    # FROM is the exception the FROM itself needs.
    last_run = max(i for i, one in enumerate(instrs) if one.startswith("RUN "))
    for i, one in enumerate(instrs):
        if start is not None and i < start:
            continue
        found = re.match(r'ARG (BUILD_\w+)', one)
        if found and i < last_run:
            problems.append(
                "ARG %s sits above the last RUN. Its value changes on every "
                "build, so every layer under it is rebuilt and re-sent. Keep "
                "the BUILD_* ARGs with the LABEL at the bottom." % found.group(1))
    return problems


def test_the_dockerfile_builds_the_three_layers_in_order() -> None:
    problems = guard_failures(DOCKERFILE.read_text(encoding="utf-8"),
                              DEPENDS.read_text(encoding="utf-8"))
    assert problems == [], "\n\n".join(problems)


def source_deb(depends: str) -> str | None:
    """The `.deb` version the list says it was generated from, or None.

    This is provenance, not a pin. The list is regenerated when the `.deb`
    is pinned, and until the bump workflow does that itself -- #153's
    sibling issue, out of scope on #154 -- a bump can leave it behind. The
    static tier does **not** fail on that: `build-amd64` and
    `build-aarch64` declare `needs: static`, so a red static tier would
    cost the weekly bump PR the image build that proves the new SHA256,
    the nightly URL and the new package's dependency resolution -- the
    gate ADR 0002 rests on -- to catch a staleness whose whole cost is
    that a moved dependency is resolved into layer (b) instead of (a).
    A list behind the pin makes (b) bigger and nothing else.
    """
    found = re.search(r"^# source: odoo_(18\.0\.\d{8})_all\.deb$", depends,
                      re.M)
    return found.group(1) if found else None


def test_the_dependency_list_records_the_deb_it_came_from() -> None:
    text = DEPENDS.read_text(encoding="utf-8")
    assert source_deb(text), \
        "the file says which .deb it was generated from, in the shape the " \
        "bump workflow will one day rewrite"
    entries = read_depends(text)
    assert len(entries) > 40, "the Odoo .deb has dozens of Depends"
    # The two normalizations the pinned .deb actually needs, spelled out so
    # that losing them is a failure and not a silent change of meaning.
    notes = dict(entries)
    assert notes["python3"]["qualifier"] == ":any"
    assert notes["postgresql-client"]["satisfied-by"] == "postgresql-client-16"
    assert notes["python3-lxml"]["alternatives"] == \
        "python3-lxml-html-clean | python3-lxml", \
        "bookworm has no python3-lxml-html-clean, so apt resolves python3-lxml"


def test_an_adr_records_the_rule_and_the_numbers_it_rests_on() -> None:
    adrs = sorted(ADR_DIR.glob("0013-*.md"))
    assert adrs, "issue #154 lands ADR 0013"
    text = adrs[0].read_text(encoding="utf-8")
    assert "status: accepted" in text
    # Collapsed, so a figure that happens to wrap still counts.
    flat = " ".join(text.split())
    # The measurements the split was decided on, and the refresh rule that
    # pays for the security fixes (a) stops picking up by accident.
    # Whole phrases, not bare numbers: "75" alone would be satisfied by the
    # "759 MiB" two tokens above it and would prove nothing.
    for token in ("759 MiB", "724 MiB was new", "693.3 MiB",
                  "689.1 MiB", "120\u2013200 KiB/s",
                  "75 unbroken minutes", "207 MiB", "235 MiB", "271 MiB",
                  "20 MiB", "LAYER_A_REFRESH", "#153"):
        assert token in flat, "the ADR must record %r" % token


def test_a_dependency_may_be_deferred_to_layer_b_but_not_dropped() -> None:
    # What a bump does when the nightly gains a dependency: record it,
    # mark it deferred, and let apt install it into (b) until an event
    # rebuilds (a) anyway. Without the note the same line must turn red.
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    depends = DEPENDS.read_text(encoding="utf-8")
    added = depends.replace("python3-cbor2\n", "python3-brand-new  # deferred: "
                            "folded into (a) at the next base bump\n"
                            "python3-cbor2\n", 1)
    assert guard_failures(dockerfile, added) == []
    plain = depends.replace("python3-cbor2\n",
                            "python3-brand-new\npython3-cbor2\n", 1)
    problems = guard_failures(dockerfile, plain)
    assert any("python3-brand-new" in one for one in problems), problems
    # A reason is prose and may contain a semicolon, which separates notes.
    prose = depends.replace("python3-cbor2\n", "python3-brand-new  # deferred: "
                            "not in (a) yet; folded in at the next base bump\n"
                            "python3-cbor2\n", 1)
    assert guard_failures(dockerfile, prose) == []
    # A misspelled kind after the first note is a typo, not prose: silently
    # accepting it would install the package after all.
    typo = depends.replace("python3-cbor2\n", "python3-brand-new  # "
                           "alternatives: a | b; defered: later\n"
                           "python3-cbor2\n", 1)
    assert any("defered" in one for one in guard_failures(dockerfile, typo))


def test_a_dependency_the_nightly_drops_may_stay_in_layer_a() -> None:
    # The mirror of `deferred`: the nightly stops depending on a package
    # that (a) installs. Removing it from (a) would rebuild the big layer
    # on a routine bump, so the line stays with a `dropped` note.
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    depends = DEPENDS.read_text(encoding="utf-8")
    dropped = depends.replace("python3-cbor2\n", "python3-cbor2  # dropped: "
                              "gone from Depends, removed at the next base "
                              "bump\n", 1)
    assert guard_failures(dockerfile, dropped) == []
    # But not silently: a note with no reason is a failure.
    silent = depends.replace("python3-cbor2\n", "python3-cbor2  # dropped:\n", 1)
    assert any("python3-cbor2" in one
               for one in guard_failures(dockerfile, silent))


def test_layer_c_may_add_a_package_whose_name_extends_one_in_layer_a() -> None:
    # ADR 0013 sends a small addition to (c). `postgresql-16-pgvector` is
    # such an addition, and it must not make (a) ambiguous.
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    added = dockerfile.replace("        python3-yaml \\\n",
                               "        postgresql-16-pgvector \\\n"
                               "        python3-yaml \\\n", 1)
    assert added != dockerfile
    assert guard_failures(added, DEPENDS.read_text(encoding="utf-8")) == []


# ── self-tests: the mutations that must turn the guard red ─────────────


def _line_starting(text: str, prefix: str) -> str:
    for line in text.splitlines(keepends=True):
        if line.startswith(prefix):
            return line
    raise AssertionError("no line starts with %r" % prefix)


def _layer_a_run(text: str) -> str:
    start = text.index("RUN ", text.index('ARG LAYER_A_REFRESH='))
    return text[start:text.index("\n\n", start)]


def _arg_moved_above_layer_a(text: str) -> str:
    line = _line_starting(text, "ARG ODOO_DEB_VERSION=")
    return text.replace(line, "", 1).replace(
        "ARG LAYER_A_REFRESH=", line + "ARG LAYER_A_REFRESH=", 1)


def _package_added_to_layer_a(text: str) -> str:
    run = _layer_a_run(text)
    return text.replace(run, run.replace(
        "    && apt-get clean", "        vim \\\n    && apt-get clean"), 1)


def _apt_flag_changed_in_layer_a(text: str) -> str:
    run = _layer_a_run(text)
    return text.replace(run, run.replace(
        "-y --no-install-recommends", "-y", 1), 1)


def _run_inserted_above_layer_a(text: str) -> str:
    return text.replace("ARG LAYER_A_REFRESH=",
                        "RUN echo layered\n\nARG LAYER_A_REFRESH=", 1)


def _layer_c_moved_below_the_overlay(text: str) -> str:
    end = text.rindex("python3-pycryptodome")
    start = text.rindex("RUN ", 0, end)
    run = text[start:text.index("\n\n", start)]
    overlay = "COPY rootfs/ /"
    return text.replace(run + "\n\n", "", 1).replace(
        overlay, overlay + "\n\n" + run, 1)


def _a_per_build_arg_moved_above_layer_a(text: str) -> str:
    line = _line_starting(text, "ARG BUILD_DATE")
    return text.replace(line, "", 1).replace(
        "ARG LAYER_A_REFRESH=", line + "ARG LAYER_A_REFRESH=", 1)


def _a_fourth_apt_run_below_the_overlay(text: str) -> str:
    overlay = "COPY rootfs/ /"
    return text.replace(overlay, overlay + "\n\nRUN apt-get update \\\n"
                        "    && apt-get install -y --no-install-recommends "
                        "vim \\\n    && apt-get clean \\\n"
                        "    && rm -rf /var/lib/apt/lists/*", 1)


MUTATIONS = {
    "an ARG moved above (a)": _arg_moved_above_layer_a,
    "a package added to (a)": _package_added_to_layer_a,
    "a changed apt flag": _apt_flag_changed_in_layer_a,
    "a RUN inserted above (a)": _run_inserted_above_layer_a,
    # Three more, for the assertions the four above never reach.
    "(c) moved below the rootfs overlay": _layer_c_moved_below_the_overlay,
    "a per-build ARG moved above (a)": _a_per_build_arg_moved_above_layer_a,
    "a fourth apt RUN below the overlay": _a_fourth_apt_run_below_the_overlay,
}


def test_every_mutation_of_the_layout_turns_the_guard_red() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    depends = DEPENDS.read_text(encoding="utf-8")
    for what, mutate in MUTATIONS.items():
        mutated = mutate(text)
        assert mutated != text, what
        problems = guard_failures(mutated, depends)
        assert problems, "%s left the guard green" % what


def test_a_bot_style_rewrite_of_the_pinned_values_stays_green() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    rewritten = text
    for name, value in (("BASE_IMAGE_TAG", "bookworm-2026.12.1"),
                        ("ODOO_DEB_VERSION", "18.0.20261231"),
                        ("ODOO_DEB_SHA256", "0" * 64),
                        ("LAYER_A_REFRESH", "2027-01-05")):
        rewritten = re.sub(r'^ARG %s="[^"]*"$' % name,
                           'ARG %s="%s"' % (name, value), rewritten, flags=re.M)
    assert rewritten != text, "the rewrite must actually change the file"
    depends = DEPENDS.read_text(encoding="utf-8")
    problems = guard_failures(rewritten, depends)
    assert problems == [], "\n\n".join(problems)
    # The layout survives a bump untouched, which is the point of where the
    # ODOO_DEB_* ARGs sit, and so does the whole static tier: a bump PR
    # reaches the image build that proves it. The dependency list is the
    # one thing the bump leaves behind -- it still names the old package
    # until it is regenerated, and that costs layer (b) size, not a gate.
    pinned = re.search(r'^ARG ODOO_DEB_VERSION="([^"]*)"$', rewritten, re.M)
    assert source_deb(depends) != pinned.group(1), \
        "the rewrite must move the pin away from the recorded source"
