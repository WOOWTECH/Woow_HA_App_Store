from importlib.machinery import SourceFileLoader
from pathlib import Path

module = SourceFileLoader(
    "odoo_jsonrpc_filter",
    str(Path(__file__).parents[1] / "rootfs/usr/local/bin/odoo-jsonrpc-filter"),
).load_module()

assert module.contains_db_service({"params": {"service": "db", "method": "list"}})
assert module.contains_db_service([
    {"params": {"service": "object", "method": "execute"}},
    {"params": {"service": "db", "method": "drop"}},
])
assert not module.contains_db_service({"params": {"service": "object", "method": "execute_kw"}})
assert not module.contains_db_service({"params": {"service": "common", "method": "version"}})
assert not module.contains_db_service({"jsonrpc": "2.0", "method": "call", "params": {}})
print("jsonrpc filter tests passed")
