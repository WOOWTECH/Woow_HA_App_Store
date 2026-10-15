"""Pinned n8n metadata-only reads. No new writer grants or backend overrides."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema
from .expansion import Folders as PreviousFolders, Segment
from .policy import Tool


class Args(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


def omitted():
    return Field(default=None, exclude_if=lambda value: value is None,
                 json_schema_extra=lambda schema: schema.pop('default', None))


class Catalog(Args):
    kind: Literal['tags']
    query: Annotated[str, Field(max_length=256)] | SkipJsonSchema[None] = omitted()
    limit: int = Field(default=20, ge=1, le=250)

    @field_validator('query')
    @classmethod
    def no_null(cls, value):
        if value is None:
            raise ValueError('omit optional fields instead of null')
        return value


# Portable schemas: JSON Schema regex '$' can accept a trailing line terminator.
StrictSegment = Annotated[Segment, Field(json_schema_extra={'not': {'pattern': r'[^A-Za-z0-9_-]'}})]


class Executions(Args):
    action: Literal['list']
    limit: int = Field(default=20, ge=1, le=100)
    includeData: bool = Field(default=False, json_schema_extra={'const': False})
    cursor: Annotated[str, Field(min_length=1, max_length=512, pattern=r'^[A-Za-z0-9_+=-]+$', json_schema_extra={'not': {'pattern': r'[^A-Za-z0-9_+=-]'}})] | SkipJsonSchema[None] = omitted()
    workflowId: StrictSegment | SkipJsonSchema[None] = omitted()
    projectId: StrictSegment | SkipJsonSchema[None] = omitted()
    status: Literal['success', 'error', 'waiting'] | SkipJsonSchema[None] = omitted()

    @field_validator('cursor', 'workflowId', 'projectId', 'status')
    @classmethod
    def no_null(cls, value):
        if value is None:
            raise ValueError('omit optional fields instead of null')
        return value

    @field_validator('includeData')
    @classmethod
    def metadata_only(cls, value):
        if value:
            raise ValueError('execution payloads are withheld')
        return value

    @field_validator('projectId')
    @classmethod
    def explicit_project(cls, value):
        if value == 'personal':
            raise ValueError('explicit project ID required')
        return value

    model_config = ConfigDict(strict=True, extra='forbid', json_schema_extra=lambda schema: schema['properties']['projectId'].update({'allOf': [{'not': {'const': 'personal'}}]}))


class Health(Args):
    mode: Literal['status'] = 'status'


def folder_schema(schema):
    fields = {'folderId', 'name'}
    rules = {'list': (), 'create': ('name',), 'rename': ('folderId', 'name'), 'get': ('folderId',)}
    schema['oneOf'] = []
    for action, required in rules.items():
        properties = {'action': {'const': action}, **{
            field: {'type': 'string' if field in required else 'null'} for field in fields}}
        if action == 'get':
            properties['projectId'] = {'not': {'anyOf': [{'const': 'personal'}, {'pattern': r'[^A-Za-z0-9_-]'}]}}
            properties['folderId']['not'] = {'pattern': r'[^A-Za-z0-9_-]'}
        schema['oneOf'].append({'properties': properties,
            'required': ['action', *required, *(['projectId'] if action == 'get' else [])]})


class Folders(PreviousFolders):
    model_config = ConfigDict(strict=True, extra='forbid', json_schema_extra=folder_schema)
    action: Literal['list', 'create', 'rename', 'get']

    @model_validator(mode='after')
    def branch(self):
        if (self.action in ('get', 'rename')) != (self.folderId is not None):
            raise ValueError('folderId required only for get/rename')
        if (self.action in ('create', 'rename')) != (self.name is not None):
            raise ValueError('name required only for create/rename')
        if self.action == 'get' and self.projectId == 'personal':
            raise ValueError('explicit project ID required')
        return self


N8N_TOOLS = {
    'n8n_list_catalog': Tool(Catalog, requires_backend=True),
    'n8n_executions': Tool(Executions, selector='action', requires_backend=True),
    'n8n_health_check': Tool(Health, requires_backend=True),
    'n8n_manage_folders': Tool(Folders, selector='action', write_operations=('create', 'rename'),
                               backend_required_operations=('get',)),
}
