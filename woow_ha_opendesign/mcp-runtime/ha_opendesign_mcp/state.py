"""0.2.6: the built-in server keeps its schema 3 state (0.2.0-0.2.5) and never migrates it.

The runtime pinned since 0.2.6 (WOOWTECH/Woow_ha_mcp_addons 0.4.0) stores schema 4 for the standalone MCP add-ons, and
its products.ProductStore migrates a schema 3 state once on open: every write granted, writes_enabled on and every
disabled tool enabled again (owner decision 2026-10-15 for those add-ons; their 0.3.x run_product adds an upgrade
review page before it). The built-in server never had a schema 4, and an update must keep what its administrator chose
(as for 0.2.4 and 0.2.5: an update from 0.2.1 or later migrates nothing and grants nothing). So this module keeps the
schema 3 model that 0.2.0-0.2.5 stored (the vendored 0.1.14 products.ProductState), restricted to this one product:

- BuiltinState: the same keys and rules as before: the vendored config.State fields plus enabled_write_tools,
  product ('opendesign' only) and the typed OpenDesign connection; grants only for the writers of this add-on's table
  (surface.TABLE). No schema 4 key (denied_operations, mcp_access_token) exists, so the vendored gateway reports no
  operation denies and refuses a policy that carries them.
- BuiltinStore: the vendored config.Store (single writer lock, no-follow reads, atomic durable writes) for exactly
  this model. A new state is the same as 0.2.5's (no grant; defaults.apply() grants the three writers once). A stored
  schema 3 state is loaded as it is; anything else (a schema 4 state from a standalone add-on's directory, an older
  schema, another product) is refused like any incompatible state (ConfigError, manual recovery), never rewritten.

surface.install() must run before a state is validated (the grants are checked against TABLE).
"""
import secrets
from typing import Literal

from pydantic import Field, field_validator, model_validator

from mcp_admin_core.config import State, Store
from mcp_admin_core.products import OpenDesignConnection

from . import PRODUCT

SCHEMA = 3


class BuiltinState(State):
    schema_version: int = SCHEMA
    enabled_write_tools: list[str] = Field(default_factory=list)
    product: Literal['opendesign']
    connection: OpenDesignConnection | None = Field(default=None, repr=False)

    @field_validator('schema_version')
    @classmethod
    def version(cls, value):
        if value != SCHEMA:
            raise ValueError('unsupported schema')
        return value

    @model_validator(mode='before')
    @classmethod
    def typed_connection(cls, value):
        if not isinstance(value, dict):
            return value
        if value.get('backend_url') is not None or value.get('backend_key') is not None:
            raise ValueError('product uses typed connection only')
        connection = value.get('connection')
        if connection is not None:
            value = {**value, 'connection': OpenDesignConnection.model_validate(connection)}
        return value

    @model_validator(mode='after')
    def reviewed_grants(self):
        from .surface import TABLE
        allowed = {grant for name, tool in TABLE.items() for grant in tool.grants(name)}
        if len(set(self.enabled_write_tools)) != len(self.enabled_write_tools) or set(self.enabled_write_tools) - allowed:
            raise ValueError('unknown or wrong-product write grant')
        return self

    @property
    def configured(self):
        return self.connection is not None


class BuiltinStore(Store):
    """config.Store for BuiltinState; product is read by the vendored gateway (n8n request bounds: not this one)."""

    product = PRODUCT

    def _initial_state(self):
        return BuiltinState(product=PRODUCT, token=secrets.token_urlsafe(32), child_token=secrets.token_urlsafe(32))

    def _decode(self, value):
        if (not isinstance(value, dict) or set(value) != set(BuiltinState.model_fields)
                or type(value.get('schema_version')) is not int or value['schema_version'] != SCHEMA
                or value.get('product') != PRODUCT):
            raise ValueError('wrong product, schema or keys')
        return BuiltinState.model_validate(value)
