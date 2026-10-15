"""B1 pinned-source subsets: pure previews, partner counts, safe draft graphs.

Preview payloads are data, never execution authority. Graph writes only create
manual-trigger/no-op drafts; there is no update, activation or credential path.
"""
from typing import Annotated, Literal
from pydantic import ConfigDict, Field, model_validator, AfterValidator
from .expansion import Args, Partner, Record, PartnerField, Positive, Text, SearchRecords
from .policy import Tool


def false_only(value):
    if value is not False:
        raise ValueError('must remain false')
    return value


FalseOnly = Annotated[bool, Field(json_schema_extra={'const': False}), AfterValidator(false_only)]


class IdCondition(Args):
    field: Literal['id']
    operator: Literal['=', '!=']
    value: Positive


class ActiveCondition(Args):
    field: Literal['active']
    operator: Literal['=', '!=']
    value: bool


class NameCondition(Args):
    field: Literal['name', 'display_name']
    operator: Literal['=', '!=', 'ilike']
    value: str = Field(max_length=256)


class BuildDomain(Args):
    conditions: list[IdCondition | ActiveCondition | NameCondition] = Field(max_length=10)
    logical_operator: Literal['and', 'or'] = 'and'
    fields_metadata: None = None


class Domain(Args):
    domain: list[list] = Field(default_factory=list, max_length=10,
        json_schema_extra=SearchRecords.model_fields['domain'].json_schema_extra)

    @model_validator(mode='after')
    def domain_shape(self):
        SearchRecords(model='res.partner', fields=['id'], domain=self.domain)
        return self


class PreviewKwargs(Domain):
    fields: list[PartnerField] | None = Field(default=None, min_length=1, max_length=4, exclude_if=lambda v: v is None)
    limit: Annotated[int, Field(ge=1, le=100)] | None = Field(default=None, exclude_if=lambda v: v is None)
    offset: Annotated[int, Field(ge=0, le=10000)] | None = Field(default=None, exclude_if=lambda v: v is None)


def preview_schema(schema, cls):
    schema['allOf'] = [{'if': {'properties': {'method': {'const': 'search_count'}}},
                        'then': {'properties': {'kwargs': {'properties': {
                            'fields': False, 'limit': False, 'offset': False}}}}}]


class Preview(Partner):
    model_config = ConfigDict(strict=True, extra='forbid', json_schema_extra=preview_schema)
    method: Literal['search_read', 'search_count']
    args: None = None
    kwargs: PreviewKwargs = Field(default_factory=PreviewKwargs)

    @model_validator(mode='after')
    def method_kwargs(self):
        # search_count doesn't accept fields/limit/offset, even null values.
        if self.method == 'search_count' and self.kwargs.model_fields_set - {'domain'}:
            raise ValueError('search_count accepts only domain')
        return self

class Json2Preview(Preview):
    base_url: None = None
    database: None = None
    include_database_header: bool = True


class DiagnosePreview(Preview):
    transport: Literal['auto', 'xmlrpc', 'jsonrpc', 'json2'] = 'auto'
    target_version: Literal['18', '19', '20'] | None = None
    observed_error: None = None
    include_debug: FalseOnly = False
    metadata: None = None
    use_live_metadata: FalseOnly = False


class Counts(Domain, Partner):
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    order: None = None


class OdooCounts(Counts):
    group_by: list[Literal['active']] = Field(min_length=1, max_length=1)
    measures: list[Literal['id:count']] = Field(default_factory=lambda: ['id:count'], min_length=1, max_length=1)
    lazy: FalseOnly = False
    instance: Literal['default'] | None = None


class ManageCounts(Counts):
    groupby: list[Literal['active']] = Field(min_length=1, max_length=1)
    aggregates: list[Literal['id:count']] = Field(default_factory=lambda: ['id:count'], min_length=1, max_length=1)


class InternalNote(Record):
    body: str = Field(min_length=1, max_length=4000)
    subtype: Literal['note'] = 'note'
    message_type: Literal['comment'] = 'comment'
    partner_ids: None = None
    attachment_ids: None = None
    body_is_html: FalseOnly = False

    @model_validator(mode='after')
    def nonempty(self):
        if not self.body.strip():
            raise ValueError('empty note')
        return self


# Exclude JS object prototype keys at every graph dictionary key/name boundary.
def graph_name(value):
    if value in ('__proto__', 'prototype', 'constructor'):
        raise ValueError('reserved graph name')
    return value


# JSON-schema regex engines may match $ before a final line terminator; Rust's
# runtime pattern is strict. Forbid every non-ASCII-allowed character anywhere
# in the advertised schema too, including propertyNames for connection keys.
GraphName = Annotated[str, Field(min_length=1, max_length=64,
    pattern=r'^[A-Za-z][A-Za-z0-9 _-]*$', json_schema_extra={
        'not': {'enum': ['__proto__', 'prototype', 'constructor']},
        'allOf': [{'not': {'pattern': r'[^A-Za-z0-9 _-]'}}],
    }), AfterValidator(graph_name)]


class SafeNode(Args):
    id: GraphName
    name: GraphName
    type: Literal['n8n-nodes-base.manualTrigger', 'n8n-nodes-base.noOp']
    typeVersion: int = Field(ge=1, le=1)
    position: list[Annotated[float, Field(ge=-10000, le=10000)]] = Field(min_length=2, max_length=2)
    parameters: Args


class Edge(Args):
    node: GraphName
    type: Literal['main']
    index: int = Field(ge=0, le=0)


class Outputs(Args):
    main: list[Annotated[list[Edge], Field(max_length=20)]] = Field(min_length=1, max_length=1)


class DraftGraph(Args):
    name: Text
    nodes: list[SafeNode] = Field(min_length=2, max_length=20)
    # patternProperties types matching keys but leaves unmatched keys open by default.
    connections: dict[GraphName, Outputs] = Field(max_length=20,
        json_schema_extra={'additionalProperties': False})

    @model_validator(mode='after')
    def graph_scope(self):
        names = {node.name for node in self.nodes}
        if len(names) != len(self.nodes) or len({n.id for n in self.nodes}) != len(self.nodes):
            raise ValueError('duplicate nodes')
        if any(source not in names or any(edge.node not in names for edge in outputs.main[0])
               for source, outputs in self.connections.items()):
            raise ValueError('unknown connection node')
        return self


class ValidateNode(Args):
    nodeType: Literal['nodes-base.manualTrigger', 'nodes-base.noOp']
    config: Args
    mode: Literal['full', 'minimal'] = 'full'
    profile: Literal['strict', 'runtime', 'ai-friendly', 'minimal'] = 'ai-friendly'


class ValidationOptions(Args):
    validateNodes: bool = True
    validateConnections: bool = True
    validateExpressions: bool = True
    profile: Literal['minimal', 'runtime', 'ai-friendly', 'strict'] = 'runtime'


class ValidateWorkflow(Args):
    workflow: DraftGraph
    options: ValidationOptions = Field(default_factory=ValidationOptions)


N8N_TOOLS = {
    'validate_node': Tool(ValidateNode), 'validate_workflow': Tool(ValidateWorkflow),
    'n8n_create_workflow': Tool(DraftGraph, write=True),
}


def expand_tools(tools):
    tools['odoo'].update({
        'build_domain': Tool(BuildDomain), 'generate_json2_payload': Tool(Json2Preview),
        'diagnose_odoo_call': Tool(DiagnosePreview), 'aggregate_records': Tool(OdooCounts),
    })
    tools['odoo-manage'].update({
        'aggregate_records': Tool(ManageCounts), 'list_resource_templates': Tool(Args),
        'post_message': Tool(InternalNote, write=True),
    })
