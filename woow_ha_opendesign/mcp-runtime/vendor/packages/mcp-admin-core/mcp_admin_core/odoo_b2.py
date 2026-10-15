"""B2 metadata-only partner topology and required-value counts, not broad reads."""
from typing import Annotated, Literal
from pydantic import AfterValidator, Field
from .expansion import Args, Partner
from .policy import Tool


def true_only(value):
    if value is not True:
        raise ValueError('must remain true')
    return value


TrueOnly = Annotated[bool, Field(json_schema_extra={'const': True}), AfterValidator(true_only)]


class Catalog(Args):
    query: None = None
    models: list[Literal['res.partner']] = Field(default_factory=lambda: ['res.partner'], min_length=1, max_length=1)
    include_fields: bool = False
    refresh: bool = False
    limit: int = Field(default=1, ge=1, le=1)
    instance: Literal['default'] | None = None


class Relationships(Partner):
    fields_metadata: None = None
    include_readonly: bool = True
    include_computed: TrueOnly = True
    use_live_metadata: TrueOnly = True
    instance: Literal['default'] | None = None


class Quality(Partner):
    checks: list[Literal['missing_required']] = Field(default_factory=lambda: ['missing_required'], min_length=1, max_length=1)
    key_fields: list[Literal['name']] = Field(default_factory=lambda: ['name'], min_length=1, max_length=1)
    sample_limit: int = Field(default=100, ge=1, le=100)
    instance: Literal['default'] | None = None


TOOLS = {'schema_catalog': Tool(Catalog), 'inspect_model_relationships': Tool(Relationships),
         'data_quality_report': Tool(Quality)}
