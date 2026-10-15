"""Reviewed bounded subsets of pinned handlers, never generated authorization.

Partner scope is deliberately id/display_name/name/active only. No arbitrary
models, contexts, methods, credentials, filenames, URLs or agent execution.
"""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .policy import Tool


def branch_schema(schema, cls):
    """Describe the conditional fields the model's validators enforce before dispatch in its JSON schema (the
    validated contract; 0.1.6: tools/list declares these branches as description clauses, policy.flat_schema)."""
    rules = {
        'Skill': {'list': (), 'enable': ('name',), 'disable': ('name',)},
        'Toolsets': {'list': (), 'enable': ('toolset',), 'disable': ('toolset',)},
        'Session': {'list': (), 'delete': ('session_id',)},
        'Cron': {'list': (), 'delete': ('job_id',), 'pause': ('job_id',)},
        'Folders': {'list': (), 'create': ('name',), 'rename': ('folderId', 'name')},
    }.get(cls.__name__)
    if rules:
        fields = {field for required in rules.values() for field in required}
        default = schema['properties']['action'].get('default')
        schema['oneOf'] = [
            {'properties': {'action': {'const': action}, **{
                field: ({'type': 'string'} if field in required else {'type': 'null'}) for field in fields}},
             'required': list(required) + ([] if action == default else ['action'])}
            for action, required in rules.items()]


class Args(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', json_schema_extra=branch_schema)


Segment = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]
Text = Annotated[str, Field(min_length=1, max_length=256)]
Positive = Annotated[int, Field(ge=1, le=2147483647)]
PartnerField = Literal['id', 'name', 'display_name', 'active']


class Partner(Args):
    model: Literal['res.partner']


class Record(Partner):
    record_id: Positive


class ReadRecord(Record):
    fields: list[PartnerField] = Field(min_length=1, max_length=4)


class OdooRead(ReadRecord):
    instance: Literal['default'] | None = None


class SearchRecords(Partner):
    fields: list[PartnerField] = Field(min_length=1, max_length=4)
    # Bounded conjunctive comparisons only; no dotted relation traversal,
    # arbitrary context, free-text shortcut, hierarchy operators or code.
    domain: list[list] = Field(default_factory=list, max_length=10, json_schema_extra={
        'items': {'oneOf': [
            {'type': 'array', 'minItems': 3, 'maxItems': 3, 'prefixItems': [
                {'enum': ['id']}, {'enum': ['=', '!=']}, {'type': 'integer', 'minimum': 1, 'maximum': 2147483647}]},
            {'type': 'array', 'minItems': 3, 'maxItems': 3, 'prefixItems': [
                {'enum': ['active']}, {'enum': ['=', '!=']}, {'type': 'boolean'}]},
            {'type': 'array', 'minItems': 3, 'maxItems': 3, 'prefixItems': [
                {'enum': ['name', 'display_name']}, {'enum': ['=', '!=', 'ilike']}, {'type': 'string', 'maxLength': 256}]},
        ]}})
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    order: Literal['id asc', 'id desc', 'name asc', 'name desc'] | None = None

    @model_validator(mode='after')
    def domain_shape(self):
        for clause in self.domain:
            if len(clause) != 3 or clause[0] not in ('id', 'name', 'display_name', 'active') or clause[1] not in ('=', '!=', 'ilike'):
                raise ValueError('restricted domain')
            value = clause[2]
            if clause[0] == 'id' and (type(value) is not int or not 1 <= value <= 2147483647):
                raise ValueError('invalid id')
            if clause[0] == 'active' and type(value) is not bool:
                raise ValueError('invalid active')
            if clause[0] in ('name', 'display_name') and (type(value) is not str or len(value) > 256):
                raise ValueError('invalid name')
            if clause[1] == 'ilike' and clause[0] not in ('name', 'display_name'):
                raise ValueError('invalid comparison')
        return self


class OdooSearch(SearchRecords):
    instance: Literal['default'] | None = None
    query: None = None


class Fields(Partner):
    field_names: list[PartnerField] = Field(min_length=1, max_length=4)
    relevance: Literal['top'] | None = None
    max_fields: int = Field(default=15, ge=1, le=100)
    instance: Literal['default'] | None = None


class PartnerValues(Args):
    name: Text


class CreatePartner(Partner):
    values: PartnerValues


class UpdatePartner(Record):
    values: PartnerValues


class Approval(Args):
    token: str = Field(pattern=r'^odoo-write:[a-f0-9]{32}$')


class Chatter(Record):
    body: str = Field(min_length=1, max_length=4000)
    message_type: Literal['comment'] = 'comment'
    subtype_xmlid: None = None
    partner_ids: None = None
    attachment_ids: None = None
    approval: Approval | None = None
    confirm: bool = False
    instance: Literal['default'] | None = None


class Skill(Args):
    action: Literal['list', 'enable', 'disable']
    name: Segment | None = None

    @model_validator(mode='after')
    def branch(self):
        if (self.action == 'list') != (self.name is None):
            raise ValueError('name is required only for mutations')
        return self


class Gateway(Args):
    action: Literal['status', 'restart'] = 'status'


class Toolsets(Args):
    action: Literal['list', 'enable', 'disable'] = 'list'
    toolset: Segment | None = None

    @model_validator(mode='after')
    def branch(self):
        if (self.action == 'list') != (self.toolset is None):
            raise ValueError('toolset required only for mutations')
        return self


class Session(Args):
    action: Literal['list', 'delete'] = 'list'
    session_id: Segment | None = None

    @model_validator(mode='after')
    def branch(self):
        if (self.action == 'list') != (self.session_id is None):
            raise ValueError('session_id required only for deletion')
        return self


class Cron(Args):
    action: Literal['list', 'delete', 'pause'] = 'list'
    job_id: Segment | None = None
    name: None = None
    schedule: None = None
    prompt: None = None
    enabled: bool = Field(default=True, json_schema_extra={'const': True})

    @model_validator(mode='after')
    def branch(self):
        if self.enabled is not True:
            raise ValueError('unused enabled must retain handler default')
        if (self.action == 'list') != (self.job_id is None):
            raise ValueError('job_id required only for mutation')
        return self


class Client(Args):
    clientid: Segment


class Subscribe(Client):
    topic: str = Field(min_length=1, max_length=256)
    qos: int = Field(default=0, ge=0, le=2)


class Unsubscribe(Client):
    topic: str = Field(min_length=1, max_length=256)


class Pagination(Args):
    page: int = Field(default=1, ge=1, le=10000)
    limit: int = Field(default=50, ge=1, le=200)


class Clients(Pagination):
    username: Text | None = None
    clientid: Segment | None = None
    ip_address: Text | None = None
    connected_only: bool = False


class Topics(Pagination):
    topic: Text | None = None


class Subscriptions(Topics):
    clientid: Segment | None = None
    match_topic: Text | None = None
    qos: Annotated[int, Field(ge=0, le=2)] | None = None


class Metrics(Args):
    latest_seconds: int = Field(default=3600, ge=60, le=86400)


class Alarms(Args):
    active_only: bool = True


class Teams(Args):
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=50, ge=1, le=100)
    team_alias: Text | None = None
    user_id: Segment | None = None
    organization_id: None = None


# JSON Schema engines can treat `$` as before a final newline, unlike the
# strict validator. Explicit character exclusion keeps the public schema equal.
MetadataSegment = Annotated[Segment, Field(json_schema_extra={'not': {'pattern': r'[^A-Za-z0-9_-]'}})]


class LiteLLMModelInfo(Args):
    litellm_model_id: MetadataSegment


class LiteLLMModelGroupInfo(Args):
    model_group: str = Field(min_length=1, max_length=256, pattern=r'^[A-Za-z0-9][A-Za-z0-9_./:-]*$',
                             json_schema_extra={'not': {'pattern': r'[^A-Za-z0-9_./:-]'}})


class LiteLLMTeamInfo(Args):
    team_id: MetadataSegment


class LiteLLMUserInfo(Args):
    user_id: MetadataSegment


class LiteLLMUsers(Args):
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=50, ge=1, le=100)
    role: Literal['proxy_admin', 'proxy_admin_viewer', 'internal_user', 'internal_user_viewer'] | None = None
    user_ids: list[MetadataSegment] | None = Field(default=None, min_length=1, max_length=20)
    team: MetadataSegment | None = None
    user_email: None = None
    sort_by: None = None
    sort_order: None = None


class CreateTeam(Args):
    team_alias: Text
    # No arbitrary metadata, membership/role escalation or provider URLs.
    models: list[Text] = Field(default_factory=list, max_length=20)
    max_budget: float = Field(default=0.0, ge=0, le=100000)
    tpm_limit: Annotated[int, Field(ge=0, le=1000000)] | None = None
    rpm_limit: Annotated[int, Field(ge=0, le=10000)] | None = None
    members_with_roles: None = None
    organization_id: None = None


class UpdateTeam(Args):
    team_id: Segment
    team_alias: Text
    models: None = None
    max_budget: None = None
    tpm_limit: None = None
    rpm_limit: None = None


class DeleteTeam(Args):
    team_ids: list[Segment] = Field(min_length=1, max_length=20)


class ModelId(Args):
    model_id: Segment


class Node(Args):
    nodeType: str = Field(min_length=1, max_length=128, pattern=r'^nodes-(?:base|langchain)\.[A-Za-z0-9_]+$')
    detail: Literal['minimal', 'standard'] = 'standard'
    mode: Literal['info'] = 'info'
    includeTypeInfo: bool = Field(default=False, json_schema_extra={'const': False})
    includeExamples: bool = Field(default=False, json_schema_extra={'const': False})

    @model_validator(mode='after')
    def no_extra_views(self):
        if self.includeTypeInfo or self.includeExamples:
            raise ValueError('extra views not supported')
        return self


class Workflow(Args):
    id: Segment
    mode: Literal['minimal'] = 'minimal'


class Folders(Args):
    action: Literal['list', 'create', 'rename']
    projectId: Segment = 'personal'
    folderId: Segment | None = Field(default=None, exclude_if=lambda v: v is None)
    name: Text | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode='after')
    def branch(self):
        if (self.action == 'rename') != (self.folderId is not None):
            raise ValueError('folderId required only for get/rename')
        if (self.action in ('create', 'rename')) != (self.name is not None):
            raise ValueError('name required only for create/rename')
        return self


N8N_GRANTS = frozenset(('n8n_create_workflow', 'n8n_delete_workflow', 'n8n_manage_folders:create', 'n8n_manage_folders:rename'))
N8N_TOOLS = {
    'get_node': Tool(Node),
    'n8n_get_workflow': Tool(Workflow),
    'n8n_manage_folders': Tool(Folders, selector='action', write_operations=('create', 'rename')),
}


def expand_tools(tools):
    tools['odoo'].update({
        'read_record': Tool(OdooRead), 'search_records': Tool(OdooSearch),
        'get_model_fields': Tool(Fields), 'chatter_post': Tool(Chatter, write=True),
    })
    tools['odoo-manage'].update({
        'get_record': Tool(ReadRecord), 'search_records': Tool(SearchRecords),
        'create_record': Tool(CreatePartner, write=True), 'update_record': Tool(UpdatePartner, write=True),
        'delete_record': Tool(Record, write=True),
    })
    tools['hermes'].update({
        'hermes_skill': Tool(Skill, selector='action', write_operations=('enable', 'disable')),
        'hermes_gateway': Tool(Gateway, selector='action', write_operations=('restart',)),
        'hermes_session': Tool(Session, selector='action', write_operations=('delete',)),
        'hermes_tools': Tool(Toolsets, selector='action', write_operations=('enable', 'disable')),
        'hermes_cron': Tool(Cron, selector='action', write_operations=('delete', 'pause')),
    })
    tools['opendesign']['list_runs'] = Tool(Args)
    tools['emqx'].update({
        'emqx_list_clients': Tool(Clients), 'emqx_list_topics': Tool(Topics),
        'emqx_list_subscriptions': Tool(Subscriptions), 'emqx_metrics_history': Tool(Metrics),
        'emqx_list_alarms': Tool(Alarms), 'emqx_kick_client': Tool(Client, write=True),
        'emqx_client_subscribe': Tool(Subscribe, write=True),
        'emqx_client_unsubscribe': Tool(Unsubscribe, write=True),
    })
    tools['litellm'].update({
        'litellm_list_teams': Tool(Teams), 'litellm_create_team': Tool(CreateTeam, write=True),
        'litellm_update_team': Tool(UpdateTeam, write=True), 'litellm_delete_team': Tool(DeleteTeam, write=True),
        'litellm_delete_model': Tool(ModelId, write=True),
        'litellm_model_info': Tool(LiteLLMModelInfo, requires_backend=True),
        'litellm_model_group_info': Tool(LiteLLMModelGroupInfo, requires_backend=True),
        'litellm_team_info': Tool(LiteLLMTeamInfo, requires_backend=True),
        'litellm_list_users': Tool(LiteLLMUsers, requires_backend=True),
        'litellm_user_info': Tool(LiteLLMUserInfo, requires_backend=True),
    })
