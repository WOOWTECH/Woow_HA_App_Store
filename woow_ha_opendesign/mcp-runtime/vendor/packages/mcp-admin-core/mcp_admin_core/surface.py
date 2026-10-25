"""The complete tool surface of each pinned child (owner decision 2026-10-15: the full add-on, aligned with the
original MCP servers and the PaaS woow-mcp-server; every tool open, every write on by default).

Every tool a child registers is listed and forwarded: its name, the child's own inputSchema (made provider-safe by
policy.flat_schema); the child validates arguments. n8n's reviewed output wrappers are normalized before policy
and forwarding. What the gateway still decides per tool:

- the name must be one of this product's child tools below (a tool a child adds after an upgrade stays unlisted and
  refused until it is classified here; tests/test_full_surface.py compares these names with the pinned sources);
- `disabled` (the panel's per-tool switch) always wins;
- a write tool needs its exact grant (the tool name) and a mixed tool's write operation needs `tool:operation`; a new
  state and every state migrated to schema 4 hold all of them (products.fresh_write_grants), and the panel can
  revoke each one.

The classification (read / write / mixed / unverified) is the reviewed one from scripts/tool_inventory.py (which now
imports it from here); it only decides which grants exist and which MCP hint annotations are relayed.
"""
from pydantic import BaseModel, ConfigDict

from .policy import Tool

READ = {
 'odoo': 'accounting_health_across_instances accounting_health_summary aggregate_across_instances aggregate_records analyze_upgrade_log build_domain business_pack_report data_quality_report diagnose_access diagnose_odoo_call fit_gap_report generate_json2_payload get_async_task get_model_fields get_odoo_profile health_check inspect_model_relationships knowledge_stats list_async_tasks list_instances list_models lookup_model_history read_attachment read_record receivable_payable_aging scan_addons_source schema_catalog search_across_instances search_employee search_holidays search_knowledge search_records upgrade_risk_report',
 'odoo-manage': 'aggregate_records get_record list_models list_resource_templates search_records',
 'hermes': 'hermes_inspect',
 'opendesign': 'get_file_info get_project health list_agents list_connectors list_plugins list_project_files list_projects list_runs list_skills read_file version',
 'emqx': 'emqx_authz_settings emqx_broker_stats emqx_client_subscriptions emqx_cluster_status emqx_get_client emqx_get_retained emqx_get_rule_metrics emqx_get_trace_log emqx_list_actions emqx_list_alarms emqx_list_authn emqx_list_authz_sources emqx_list_banned emqx_list_clients emqx_list_connectors emqx_list_listeners emqx_list_retained emqx_list_rules emqx_list_subscriptions emqx_list_topics emqx_list_traces emqx_metrics_current emqx_metrics_history emqx_node_detail emqx_prometheus_stats',
 'litellm': 'litellm_global_spend_report litellm_health_readiness litellm_key_info litellm_list_keys litellm_list_models litellm_list_plugins litellm_list_teams litellm_list_users litellm_model_group_info litellm_model_info litellm_plugin_info litellm_skill_hub litellm_spend_logs litellm_team_info litellm_user_info',
 'nextcloud': 'get_file_content get_file_tree list_calendars list_tasks read_text_file',
 'n8n': 'tools_documentation search_nodes get_node validate_node get_template search_templates validate_workflow n8n_get_workflow n8n_list_workflows n8n_validate_workflow n8n_health_check n8n_list_catalog',
}
WRITE = {
 'odoo': 'cancel_async_task chatter_post execute_approved_write index_knowledge submit_async_task validate_write preview_write execute_method',
 'odoo-manage': 'create_record delete_record post_message update_record call_model_method',
 'hermes': 'hermes_chat',
 'opendesign': 'create_project delete_project send_message',
 'emqx': 'emqx_ban emqx_client_subscribe emqx_client_unsubscribe emqx_create_trace emqx_delete_retained emqx_delete_trace emqx_kick_client emqx_publish emqx_publish_bulk emqx_toggle_rule emqx_unban',
 'nextcloud': 'create_text_file delete_file_checked update_text_file upload_file',
 'litellm': 'litellm_health litellm_token_counter litellm_spend_calculate litellm_add_model litellm_block_key litellm_chat_completion litellm_create_team litellm_create_user litellm_delete_key litellm_delete_model litellm_delete_plugin litellm_delete_team litellm_delete_user litellm_disable_plugin litellm_enable_plugin litellm_generate_key litellm_regenerate_key litellm_register_plugin litellm_team_member_add litellm_team_member_delete litellm_unblock_key litellm_update_key litellm_update_model litellm_update_team litellm_update_user',
 'n8n': 'n8n_manage_agents n8n_explore_node_resources n8n_create_workflow n8n_update_full_workflow n8n_update_partial_workflow n8n_delete_workflow n8n_autofix_workflow n8n_test_workflow n8n_deploy_template',
}
MIXED = {
 'odoo': '', 'odoo-manage': '',
 'hermes': 'hermes_config hermes_cron hermes_gateway hermes_mcp hermes_model hermes_session hermes_skill hermes_tools hermes_webhook',
 'opendesign': '', 'emqx': 'emqx_manage_authn_users emqx_manage_authz_rules', 'litellm': '', 'nextcloud': '',
 'n8n': 'n8n_executions n8n_evaluations n8n_workflow_versions n8n_manage_datatable n8n_manage_folders n8n_manage_credentials',
}
# These handlers are not proven non-mutating by the wrapper: granted (and revocable) as writes.
UNCERTAIN = {'emqx': 'emqx_test_rule_sql', 'litellm': '', 'n8n': 'n8n_audit_instance'}

# The operation parameter of each mixed tool, every value its source accepts, and those that only read.
SELECTORS = {
    'hermes_config': ('action', 'get set'), 'hermes_cron': ('action', 'create delete list pause resume trigger update'),
    'hermes_gateway': ('action', 'restart status'), 'hermes_mcp': ('action', 'add list remove'),
    'hermes_model': ('action', 'info list_providers set'), 'hermes_session': ('action', 'delete get list'),
    'hermes_skill': ('action', 'disable enable list'), 'hermes_tools': ('action', 'disable enable list'),
    'hermes_webhook': ('action', 'create delete enable_platform list toggle'),
    'emqx_manage_authn_users': ('operation', 'create delete read'),
    'emqx_manage_authz_rules': ('operation', 'create delete read'),
    'n8n_evaluations': ('action', 'list_runs get_run list_cases run cancel'),
    'n8n_executions': ('action', 'get list delete'),
    'n8n_manage_credentials': ('action', 'list get create update delete getSchema'),
    'n8n_manage_datatable': ('action', 'createTable listTables getTable updateTable deleteTable getRows insertRows '
                                       'updateRows upsertRows deleteRows addColumn deleteColumn renameColumn'),
    'n8n_manage_folders': ('action', 'create list get rename move delete'),
    'n8n_workflow_versions': ('mode', 'list get rollback delete prune diff'),
}
OPERATION_READS = {
    'hermes_config': ['get'], 'hermes_cron': ['list'], 'hermes_gateway': ['status'],
    'hermes_mcp': ['list'], 'hermes_model': ['info', 'list_providers'],
    'hermes_session': ['list', 'get'], 'hermes_skill': ['list'], 'hermes_tools': ['list'],
    'hermes_webhook': ['list'], 'emqx_manage_authn_users': ['read'], 'emqx_manage_authz_rules': ['read'],
    'n8n_executions': ['get', 'list'], 'n8n_evaluations': ['list_runs', 'get_run', 'list_cases'],
    'n8n_workflow_versions': ['list', 'get', 'diff'],
    'n8n_manage_datatable': ['listTables', 'getTable', 'getRows'],
    'n8n_manage_folders': ['list', 'get'], 'n8n_manage_credentials': ['list', 'get', 'getSchema'],
    'n8n_manage_agents': ['reference', 'search', 'get', 'validate', 'versions', 'discover_assets'],
}
# The source default of a mixed tool's selector (always a read; the others require the selector).
DEFAULT_OPERATIONS = {'hermes_config': 'get', 'hermes_cron': 'list', 'hermes_gateway': 'status', 'hermes_model': 'info',
                      'hermes_session': 'list', 'hermes_tools': 'list', 'hermes_webhook': 'list',
                      'n8n_executions': 'list', 'n8n_workflow_versions': 'list'}
assert all(value in OPERATION_READS[name] for name, value in DEFAULT_OPERATIONS.items())
# 0.2.2: the tools that answer without a backend (n8n-mcp's documentation tools, bundled data; the unconfigured child lists
# exactly these, tests/test_tool_snapshot.py). Every other tool requires_backend: without a configured backend the gateway
# refuses it (-32603 Backend not configured), and while the health check finds the backend unreachable it refuses it with
# the reason (-32603 Backend unreachable); neither reaches the child.
BACKEND_FREE = {'n8n': 'tools_documentation search_nodes get_node validate_node get_template search_templates validate_workflow'}
# The products whose public surface is the child's complete one. Odoo Manage (retired after 0.1.4) keeps its bounded
# 0.1.x surface (products.BOUNDED_TOOLS) and is not shipped.
FULL_PRODUCTS = ('odoo', 'n8n', 'hermes', 'opendesign', 'emqx', 'litellm', 'nextcloud')


class ChildArguments(BaseModel):
    """Arguments the child server validates itself (the tool's own inputSchema in tools/list). Any JSON object;
    forwarded unchanged."""
    model_config = ConfigDict(extra='allow')


def names(product):
    """Every tool name of the product's pinned child, by classification."""
    return {effect: mapping.get(product, '').split()
            for effect, mapping in (('read', READ), ('write', WRITE), ('mixed', MIXED), ('unverified', UNCERTAIN))}


def full_tools(product):
    """{name: Tool} for every child tool of a FULL_PRODUCTS product, in name order."""
    if product not in FULL_PRODUCTS:
        raise ValueError('not a full-surface product')
    groups = names(product)
    free = BACKEND_FREE.get(product, '').split()
    tools = {}
    for effect, members in groups.items():
        for name in members:
            exposure = ('n8n_update_partial_workflow' if product == 'n8n' and
                        name in ('n8n_workflow_versions', 'n8n_test_workflow') else None)
            if effect == 'mixed':
                selector, values = SELECTORS[name]
                reads = tuple(v for v in values.split() if v in OPERATION_READS[name])
                writes = tuple(v for v in values.split() if v not in OPERATION_READS[name])
                tool = Tool(ChildArguments, selector=selector, write_operations=writes, read_operations=reads,
                            default_operation=DEFAULT_OPERATIONS.get(name), child_schema=True,
                            requires_backend=name not in free, exposure_write_tool=exposure,
                            n8n_arguments=product == 'n8n')
            else:
                tool = Tool(ChildArguments, write=effect in ('write', 'unverified'), child_schema=True,
                            requires_backend=name not in free, exposure_write_tool=exposure,
                            n8n_arguments=product == 'n8n')
            tools[name] = tool
    return dict(sorted(tools.items()))


def listing(product):
    """0.2.2: the tools/list result tools of the product's pinned child, as the child lists them with every tool enabled
    (name, title, description, inputSchema, annotations; tool_snapshot.py, generated from the real children and kept
    equal to them by tests/test_tool_snapshot.py). The gateway answers tools/list with it, through the same filter_list
    as a child's own answer, whenever no child can answer: an unconfigured backend (no child; n8n's child then lists only
    its documentation tools) or a child that is not up. A fresh copy each call."""
    import copy
    from .tool_snapshot import LISTED
    return copy.deepcopy(LISTED[product])
