"""Policy contract for the public JSON-RPC filter: the db service is denied."""
from importlib.machinery import SourceFileLoader
from pathlib import Path

FILTER = Path(__file__).resolve().parents[1] / "rootfs/usr/local/bin/odoo-jsonrpc-filter"


def load_filter():
    return SourceFileLoader("odoo_jsonrpc_filter", str(FILTER)).load_module()


def test_db_service_is_detected_in_single_and_batched_calls() -> None:
    module = load_filter()
    assert module.contains_db_service({"params": {"service": "db", "method": "list"}})
    assert module.contains_db_service([
        {"params": {"service": "object", "method": "execute"}},
        {"params": {"service": "db", "method": "drop"}},
    ])


def test_ordinary_services_pass_through() -> None:
    module = load_filter()
    assert not module.contains_db_service({"params": {"service": "object", "method": "execute_kw"}})
    assert not module.contains_db_service({"params": {"service": "common", "method": "version"}})
    assert not module.contains_db_service({"jsonrpc": "2.0", "method": "call", "params": {}})
