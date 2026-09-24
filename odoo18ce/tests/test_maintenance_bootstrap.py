"""Canonical URL decision matrix for the maintenance bootstrap.

The bootstrap runs once per add-on start, before Odoo serves requests, and
pipes ``rootfs/usr/local/lib/odoo-maintenance.py`` into ``odoo shell`` once
per database. The decision functions in that file are pure, so the whole
matrix -- ``public_url`` set/unset x ``default_db`` set/unset x stored value
clean/leaked/install default/absent x LAN address available/unavailable -- runs here without
a live Odoo or Supervisor.
"""
import importlib.util
import itertools
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "rootfs/usr/local/lib/odoo-maintenance.py"
ACCOUNT_LIB = ROOT / "rootfs/usr/local/lib/odoo-maintenance-account.py"
BOOTSTRAP = ROOT / "rootfs/usr/local/bin/odoo-maintenance-bootstrap"

# Documentation addresses only (RFC 5737); no real host or database here.
PUBLIC = "https://odoo.example.test"
LAN_IPV4 = "192.0.2.10/24"
LAN_ORIGIN = "http://192.0.2.10:8069"
LEAKED = "https://ha.example.test/api/hassio_ingress/token-value"
CLEAN = "https://kept.example.test"
# What Odoo writes into web.base.url when it creates a database: localhost on
# the add-on's http_port. Nobody chose it and nothing outside can reach it.
INSTALL_DEFAULT = "http://localhost:8070"


def load_lib():
    spec = importlib.util.spec_from_file_location("odoo_maintenance", LIB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lib():
    return load_lib()


# --- Canonical URL choice -----------------------------------------------------

def test_public_url_wins_and_loses_its_trailing_slash(lib) -> None:
    assert lib.canonical_url(PUBLIC + "/", LAN_IPV4, "8069") == PUBLIC
    assert lib.canonical_url("  " + PUBLIC + "  ", None, None) == PUBLIC


def test_lan_fallback_strips_prefix_length_and_uses_published_port(lib) -> None:
    assert lib.canonical_url("", LAN_IPV4, "18069") == "http://192.0.2.10:18069"
    assert lib.canonical_url(None, "192.0.2.10", "8069") == LAN_ORIGIN


def test_lan_fallback_defaults_to_8069_when_the_port_mapping_is_empty(lib) -> None:
    assert lib.canonical_url("", LAN_IPV4, "") == LAN_ORIGIN
    assert lib.canonical_url("", LAN_IPV4, None) == LAN_ORIGIN
    # bashio prints `null` for a JSON null mapping.
    assert lib.canonical_url("", LAN_IPV4, "null") == LAN_ORIGIN


def test_lan_fallback_takes_the_first_address_only(lib) -> None:
    assert lib.canonical_url("", "192.0.2.10/24\n198.51.100.7/24", "") == LAN_ORIGIN


def test_no_source_means_no_canonical_url(lib) -> None:
    assert lib.canonical_url("", "", "8069") is None
    assert lib.canonical_url(None, None, None) is None
    assert lib.canonical_url("", "null", "8069") is None


# --- Leak detection -----------------------------------------------------------

@pytest.mark.parametrize("value", [
    LEAKED,
    "http://192.0.2.10:8123/api/hassio_ingress/abc/odoo",
    "/api/hassio_ingress/abc",
])
def test_ingress_token_urls_are_leaked(lib, value) -> None:
    assert lib.is_leaked(value)


@pytest.mark.parametrize("value", [PUBLIC, LAN_ORIGIN, "http://127.0.0.1:8070", "", None, False])
def test_ordinary_or_absent_values_are_not_leaked(lib, value) -> None:
    assert not lib.is_leaked(value)


# --- Odoo's install default ---------------------------------------------------

@pytest.mark.parametrize("value", [INSTALL_DEFAULT, INSTALL_DEFAULT + "/"])
def test_odoo_install_default_is_recognised(lib, value) -> None:
    assert lib.is_install_default(value)
    # #57's rule is about Ingress tokens only and stays that way.
    assert not lib.is_leaked(value)


@pytest.mark.parametrize("value", [
    PUBLIC, LAN_ORIGIN, CLEAN, LEAKED, "http://127.0.0.1:8070", "http://localhost:8069", "", None, False,
])
def test_other_values_are_not_the_install_default(lib, value) -> None:
    assert not lib.is_install_default(value)


def test_install_default_follows_the_configured_http_port(lib) -> None:
    config = (ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh").read_text(encoding="utf-8")
    port = lib.INSTALL_DEFAULT_URL.rsplit(":", 1)[1]
    assert f"http_port = {port}\n" in config


# --- Per-database decision ----------------------------------------------------

@pytest.mark.parametrize("stored", [CLEAN, LEAKED, "", None, False])
def test_canonical_url_is_written_frozen_and_becomes_the_website_domain(lib, stored) -> None:
    assert lib.decide(PUBLIC, stored) == lib.Decision("write", PUBLIC, True, PUBLIC, False)


def test_without_canonical_url_a_clean_stored_value_is_kept_and_frozen(lib) -> None:
    assert lib.decide(None, CLEAN) == lib.Decision("keep", None, True, None, False)


@pytest.mark.parametrize("stored", ["", None, False])
def test_without_canonical_url_an_absent_value_is_left_unprotected(lib, stored) -> None:
    assert lib.decide(None, stored) == lib.Decision("unprotected", None, False, None, False)


def test_without_canonical_url_the_install_default_is_not_frozen(lib) -> None:
    # Nobody chose it, so it is not kept as a Canonical URL: no freeze, and the
    # next start that has one writes it.
    assert lib.decide(None, INSTALL_DEFAULT) == lib.Decision("unprotected", None, False, None, False)


def test_without_canonical_url_the_install_default_is_reported_as_a_warning(lib, capsys) -> None:
    params = FakeParams({lib.BASE_URL_KEY: INSTALL_DEFAULT})
    decision = lib.apply(FakeEnv(params), "dbleak", None)

    assert decision.action == "unprotected"
    # Left in place and not frozen.
    assert params.values == {lib.BASE_URL_KEY: INSTALL_DEFAULT}
    line = capsys.readouterr().out.strip()
    assert line.startswith("maintenance db=dbleak: WARNING")
    assert INSTALL_DEFAULT in line


def test_without_canonical_url_a_leaked_value_is_removed_not_kept(lib) -> None:
    # "treated as absent": nothing replaces it, nothing freezes it, and the
    # token must not stay in the database.
    assert lib.decide(None, LEAKED) == lib.Decision("unprotected", None, False, None, True)


class FakeParams:
    """The slice of ir.config_parameter that apply() touches."""

    def __init__(self, values):
        self.values = dict(values)

    def sudo(self):
        return self

    def get_param(self, key):
        return self.values.get(key)

    def set_param(self, key, value):
        self.values[key] = value


class FakeEnv:
    def __init__(self, params):
        self.params = params

    def __getitem__(self, model):
        assert model == "ir.config_parameter"
        return self.params


# --- The full matrix ----------------------------------------------------------

STORED = {"clean": CLEAN, "leaked": LEAKED, "install_default": INSTALL_DEFAULT, "absent": False}


@pytest.mark.parametrize(
    "public_url,default_db,stored,lan",
    list(itertools.product([PUBLIC, ""], ["example_db", ""], list(STORED), [LAN_IPV4, ""])),
)
def test_decision_matrix(lib, public_url, default_db, stored, lan) -> None:
    # default_db is an input of the bootstrap but not of the URL lock: the
    # same decision must come out whether it is set or not, which is what
    # this axis proves (the bash gates only the test account on it).
    canonical = lib.canonical_url(public_url, lan, "8069")
    decision = lib.decide(canonical, STORED[stored])

    if public_url:
        expected_url = PUBLIC
    elif lan:
        expected_url = LAN_ORIGIN
    else:
        expected_url = None

    if expected_url:
        # Every shape with a Canonical URL writes it, freezes it and mirrors it
        # into the website domain, whatever was stored before.
        assert decision == lib.Decision("write", expected_url, True, expected_url, False)
    elif stored == "clean":
        assert decision == lib.Decision("keep", None, True, None, False)
    else:
        assert decision == lib.Decision("unprotected", None, False, None, stored == "leaked")
    assert decision.freeze == (decision.action != "unprotected")


# --- Shipped-file contracts ---------------------------------------------------

def test_bootstrap_processes_every_database_and_never_requires_default_db() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    assert "pg_database" in script
    assert "ir_config_parameter" in script
    assert "/usr/local/lib/odoo-maintenance.py" in script
    assert "/usr/local/lib/odoo-maintenance-account.py" in script
    # Issue #108: the LAN address is the one cont-init settled on this start,
    # handed over through the container environment. The bootstrap does not
    # retry on its own (ADR 0006: one value per start), and only asks the
    # Supervisor itself when it runs outside a start, with nothing published.
    assert 'if [ "${WOOW_CANONICAL_SETTLED:-}" = 1 ]' in script
    assert 'LAN_IPV4="${WOOW_LAN_IPV4:-}"' in script
    assert 'PUBLISHED_PORT="${WOOW_LAN_PORT:-}"' in script
    # Never a second derivation (ADR 0006): the bootstrap neither reads the
    # Supervisor nor waits on it; without the marker it has no LAN address.
    assert "bashio::network.ipv4_address" not in script
    assert "bashio::addon.port" not in script
    assert "woow::supervisor" not in script
    assert "published no settled Canonical URL inputs" in script
    # public_url without default_db used to be a start-up failure.
    assert "default_db is required" not in script
    # A failed database listing is reported, not mistaken for "no database".
    assert "databases could not be listed" in script
    # The test account stays gated on default_db and the file survives a skip.
    assert 'if [ -z "${DB_NAME}" ]' in script
    assert "the file is kept for the next start" in script
    # The file policy violations stay fatal; everything else exits zero.
    assert "must be owned by root with mode 0600" in script
    assert "must contain at least 20 characters" in script
    assert script.rstrip().endswith("exit 0")


def test_account_lib_keeps_the_privilege_rules() -> None:
    account = ACCOUNT_LIB.read_text(encoding="utf-8")
    assert "base.group_system" in account
    assert "base.group_erp_manager" in account
    assert "no_reset_password" in account
