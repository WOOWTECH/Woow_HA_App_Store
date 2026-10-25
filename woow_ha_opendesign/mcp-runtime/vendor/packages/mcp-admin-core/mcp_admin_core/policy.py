"""Audited dispatch allowlist. Tool advertisements are not authorization."""
from dataclasses import dataclass
import functools
import json
import re
from typing import Literal, Mapping, get_args, get_origin

from pydantic import BaseModel, ValidationError

from .config import State


class Denied(ValueError):
    pass


class UnknownMethod(Denied):
    """0.1.13: a well-formed request (string or integer id) or notification whose method the gateway does not serve.

    The gateway answers it itself, before any session check, slot or child (a request: HTTP 200 with JSON-RPC -32601;
    a notification: 202). Claude.ai probes server/discover before initialize and needs a JSON-RPC answer, not 403.
    Still a Denied, so a caller that does not tell them apart keeps refusing it."""
    def __init__(self, request):
        super().__init__("method not found")
        self.request = request  # True when the message has an id (a request), False for a notification


class ToolCallRefused(Denied):
    """0.1.14: a well-formed tools/call request (string or integer id, object params with only name and arguments, a
    string name) that the policy refuses. The refusal is unchanged; only its answer is: the gateway replies HTTP 200
    with the JSON-RPC error error() builds (after the token and session checks, without a slot or the child), so a
    model sees why and can correct the call. Claude.ai showed the former HTTP 403 only as a transport failure.
    Still a Denied with the former text, so a caller that does not tell them apart keeps refusing it.

    kind is one of KINDS. error() carries the tool name and, for invalid arguments, sanitized pydantic errors: never
    an argument value (argument_errors), a backend address, a credential or a token.

    0.2.2: "backend_unreachable" is raised by the gateway itself, never by authorize: a configured backend its health
    check last found unreachable, or an MCP server (child) that is not up. reason is the health check's own text
    (credentials replaced by [REDACTED]) or the gateway's fixed MCP_SERVER_NOT_READY text."""
    KINDS = {"unknown_tool": "tool not permitted", "invalid_params": "invalid tool arguments",
             "operation_not_permitted": "operation not permitted", "backend_not_configured": "configured backend required",
             "backend_unreachable": "backend unreachable"}

    def __init__(self, kind, tool, errors=(), reason=None):
        super().__init__(self.KINDS[kind])
        self.kind = kind
        self.tool = tool
        self.errors = list(errors)
        self.reason = reason

    def error(self):
        """The JSON-RPC error object. -32602 (invalid params, MCP's code for an unknown tool or invalid arguments) when
        the request itself must change; -32603 (internal error) for a backend the add-on has not been configured with:
        the arguments are valid and no other call would succeed until an administrator configures the add-on (0.2.2: or
        until the backend is reachable again, "Backend unreachable" with data.reason)."""
        if self.kind == "unknown_tool":
            # The same answer for a tool that does not exist and one that is disabled or lacks its write grant.
            return {"code": -32602, "message": "Unknown tool", "data": {"tool": self.tool[:TOOL_NAME_LIMIT]}}
        if self.kind == "invalid_params":
            return {"code": -32602, "message": "Invalid params", "data": {"tool": self.tool, "errors": self.errors}}
        if self.kind == "operation_not_permitted":
            return {"code": -32602, "message": "Operation not permitted", "data": {"tool": self.tool, "reason": self.reason or (
                "write operation disabled by the add-on policy; an administrator can enable it in the add-on panel")}}
        if self.kind == "backend_unreachable":
            return {"code": -32603, "message": "Backend unreachable", "data": {"tool": self.tool, "reason": self.reason}}
        return {"code": -32603, "message": "Backend not configured", "data": {"tool": self.tool}}


TOOL_NAME_LIMIT = 128
ARGUMENT_ERROR_LIMIT = 20
ARGUMENT_ERROR_TEXT = 300
# pydantic error types whose message is fixed text or names only the model's own limits (allowed values, pattern,
# bounds, lengths, the model's class name); the count in too_short/too_long is a length, never content. Any other type
# (union_tag_invalid quotes the input tag; *_parsing, url_*, json_invalid, mapping_type... quote a parser's error text;
# custom types are arbitrary) gets FIXED_ARGUMENT_ERROR. value_error/assertion_error: see argument_errors().
PLAIN_ERROR_TYPES = frozenset({
    "missing", "extra_forbidden", "literal_error", "enum", "string_pattern_mismatch", "string_too_short",
    "string_too_long", "too_short", "too_long", "greater_than", "greater_than_equal", "less_than", "less_than_equal",
    "multiple_of", "finite_number", "string_type", "string_sub_type", "string_unicode", "int_type", "int_parsing",
    "int_parsing_size", "int_from_float", "float_type", "float_parsing", "bool_type", "bool_parsing", "dict_type",
    "list_type", "tuple_type", "set_type", "frozen_set_type", "model_type", "model_attributes_type", "none_required",
    "union_tag_not_found", "invalid_key", "url_type", "url_too_long", "url_scheme", "frozen_field", "is_instance_of",
    "date_type", "datetime_type", "time_type", "decimal_type", "decimal_parsing", "uuid_type", "bytes_type",
    "iterable_type", "set_item_not_hashable", "default_factory_not_called"})
FIXED_ARGUMENT_ERROR = "Value not accepted by this field's rules (see the tool's inputSchema)"
# A reviewed validator's own message (raise ValueError('duplicate nodes')): plain words, no quotes or colons. Python's
# own ValueError texts quote the value they refused (int('x'): "invalid literal for int() with base 10: 'x'").
PLAIN_VALIDATOR_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9 ,;/()._-]{0,199}")
ERROR_TYPE = re.compile(r"[a-z][a-z_]{0,63}")


@functools.lru_cache(maxsize=None)
def schema_words(model):
    """Every member name, title, $defs name and string const/enum value of `model`'s JSON schema: the only strings an
    error location may show. Others (a key the caller made up, a dict key) are the caller's input and become "*"."""
    try:
        schema = model.model_json_schema()
    except Exception:  # a model without a JSON schema: every named location part becomes "*"
        return frozenset()
    words, todo = set(), [schema]
    while todo:
        item = todo.pop()
        if isinstance(item, dict):
            for key in ("properties", "$defs"):
                if isinstance(item.get(key), dict):
                    words.update(item[key])
            words.update(value for key in ("title", "const") if isinstance(value := item.get(key), str))
            words.update(value for value in _listed(item.get("enum")) if isinstance(value, str))
            todo += list(item.values())
        elif isinstance(item, list):
            todo += item
    return frozenset(words)


def input_strings(value):
    """The caseless strings (keys and values) of the caller's arguments that a message could echo; those shorter than
    3 characters are too common in fixed text to tell apart and are not looked for."""
    found, todo = set(), [value]
    while todo:
        item = todo.pop()
        if isinstance(item, str):
            if 3 <= len(item) <= ARGUMENT_ERROR_TEXT:
                found.add(item.casefold())
        elif isinstance(item, dict):
            todo += list(item.keys()) + list(item.values())
        elif isinstance(item, list):
            todo += item
    return found


def argument_errors(model, error, arguments):
    """At most ARGUMENT_ERROR_LIMIT {field, message, type} entries for a ValidationError, without any argument value:
    pydantic's input and ctx are never read; the location keeps indexes and schema_words only; the message is kept
    for PLAIN_ERROR_TYPES and plain validator text, else (or when it contains any other caller string) fixed."""
    words, entries = schema_words(model), []
    # A caller string that is one of the model's own words (a member name, an allowed value) tells nothing new.
    echoes = input_strings(arguments) - {word.casefold() for word in words}
    for detail in error.errors(include_url=False, include_input=False, include_context=False)[:ARGUMENT_ERROR_LIMIT]:
        kind = detail.get("type") if isinstance(detail.get("type"), str) else ""
        field = ".".join(str(part) if type(part) is int or part in words else "*" for part in detail.get("loc", ()))
        text = detail.get("msg") if isinstance(detail.get("msg"), str) else ""
        if kind in ("value_error", "assertion_error"):
            own = text.split(", ", 1)[1] if ", " in text else ""
            text = text if PLAIN_VALIDATOR_TEXT.fullmatch(own) else FIXED_ARGUMENT_ERROR
        elif kind not in PLAIN_ERROR_TYPES:
            text = FIXED_ARGUMENT_ERROR
        folded = text.casefold()
        if any(echo in folded for echo in echoes):
            text = FIXED_ARGUMENT_ERROR
        entries.append({"field": field, "message": text[:ARGUMENT_ERROR_TEXT],
                        "type": kind if ERROR_TYPE.fullmatch(kind) else "invalid"})
    return entries


# Served methods; anything else is UnknownMethod (0.1.13), never forwarded.
REQUEST_METHODS = frozenset({"initialize", "ping", "tools/list", "tools/call"})
# 0.1.13: MCP reserves params._meta on every request and notification (Claude.ai sends traceparent and, for
# server/discover, client identity). It is accepted when it is an object of at most this many bytes (compact JSON)
# and removed before dispatch: no child ever gets it, so progressToken and the like never reach a child either.
META_LIMIT = 8192


def strip_meta(message, params):
    """Validate and remove params._meta; drop params altogether when it held nothing else."""
    if "_meta" not in params:
        return params
    meta = params["_meta"]
    if not isinstance(meta, dict):
        raise Denied("invalid _meta")
    try:
        size = len(json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (ValueError, RecursionError):
        raise Denied("invalid _meta") from None
    if size > META_LIMIT:
        raise Denied("_meta too large")
    del params["_meta"]
    if not params:
        del message["params"]
    return params


@dataclass(frozen=True)
class Tool:
    arguments: type[BaseModel]
    write: bool = False
    # Only the two W2a writers retain the historical global-switch semantics.
    legacy_write: bool = False
    selector: str | None = None
    write_operations: tuple[str, ...] = ()
    # Opt-in only: local tools and previously reviewed API behavior stay intact.
    requires_backend: bool = False
    backend_required_operations: tuple[str, ...] = ()
    # 0.2.0 (full surface, surface.full_tools): the child validates arguments and tools/list
    # shows the child's own inputSchema. read_operations are the selector values that only read; default_operation is
    # the source's default (a read) when the selector is omitted, None when the child requires it.
    child_schema: bool = False
    read_operations: tuple[str, ...] = ()
    default_operation: str | None = None
    # n8n's pinned child may replace the entire argument object from output JSON.
    n8n_arguments: bool = False
    # n8n's exposeToMcp flag can update a workflow while executing a read mode.
    # Reuse the existing updater permission; this adds no persisted grant.
    exposure_write_tool: str | None = None

    def __post_init__(self):
        operations = self.operations
        if (operations and not self.selector or len(set(operations)) != len(operations)
                or self.default_operation is not None and self.default_operation not in operations):
            raise ValueError('operations require an audited selector and matching default')
        if self.backend_required_operations:
            field = self.arguments.model_fields.get(self.selector)
            if (field is None or get_origin(field.annotation) is not Literal
                    or not set(self.backend_required_operations) <= set(get_args(field.annotation))):
                raise ValueError('backend operations require a matching Literal selector')

    def grants(self, name):
        return ([name] if self.write else []) + [f'{name}:{op}' for op in self.write_operations]

    @property
    def operations(self):
        """Explicitly audited operations only; never infer from arbitrary schema enums."""
        return (*self.read_operations, *self.write_operations)


def has_grant(name, tool, state):
    return name in getattr(state, 'enabled_write_tools', ()) or (tool.legacy_write and state.writes_enabled)


def enabled(name: str, tools: Mapping[str, Tool], state: State) -> bool:
    return name in tools and name not in state.disabled and (not tools[name].write or has_grant(name, tools[name], state))


def operation_enabled(name, tool, operation, state):
    return (operation in tool.operations
            and operation not in getattr(state, 'denied_operations', {}).get(name, ())
            and (operation not in tool.write_operations
                 or f'{name}:{operation}' in getattr(state, 'enabled_write_tools', ())))


def policy_enabled(name, tools, state):
    """Whether at least one audited call can pass policy (not backend readiness)."""
    if not enabled(name, tools, state):
        return False
    tool = tools[name]
    if tool.operations and (tool.child_schema or tool.read_operations):
        return any(operation_enabled(name, tool, op, state) for op in tool.operations)
    return bool(tool.operations) or not getattr(state, 'denied_operations', {}).get(name)


def check_operation_denies(name, tool, arguments, state):
    denied = getattr(state, 'denied_operations', {}).get(name, ())
    if not denied:
        return
    operation = arguments.get(tool.selector, tool.default_operation)
    # A restricted tool requires a positively audited operation. Missing required
    # selectors, explicit null, malformed/unknown values, or removed metadata may
    # otherwise bypass a deny via a child's coercion/default or a new write path.
    if type(operation) is not str or operation not in tool.operations or operation in denied:
        raise ToolCallRefused('operation_not_permitted', name, reason=(
            'operation restricted by the add-on policy; use an allowed audited operation or ask an administrator'))


def validate_operation_denies(denied, tools, state):
    """The state model validates shape first. API additions require audited metadata;
    persisted stale entries may be retained or removed, never newly introduced."""
    saved = getattr(state, 'denied_operations', {})
    for name, operations in denied.items():
        audited = tools[name].operations if name in tools else ()
        if any(op not in audited and op not in saved.get(name, ()) for op in operations):
            raise ValueError('unknown operation deny')


def authorize(message, tools: Mapping[str, Tool], state: State) -> str:
    """Authorize, replacing tool arguments with the reviewed model's wire values.

    Defaults and field-specific omission rules are applied before dispatch;
    repeated authorization is idempotent. Only authorized calls may be dispatched.
    """
    if not isinstance(message, dict) or set(message) - {"jsonrpc", "id", "method", "params"}:
        raise Denied("single JSON-RPC request required")
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        raise Denied("invalid JSON-RPC")
    method = message["method"]
    params = message.get("params", {})
    if not isinstance(params, dict):
        raise Denied("params must be object")
    if "id" not in message and method != "notifications/initialized" and method not in REQUEST_METHODS:
        raise UnknownMethod(request=False)  # e.g. notifications/cancelled: answered 202, never forwarded
    if "id" in message and type(message["id"]) in (str, int) and method not in REQUEST_METHODS:
        if method == "notifications/initialized":
            raise Denied("invalid initialized notification")
        raise UnknownMethod(request=True)  # e.g. server/discover, resources/list: JSON-RPC -32601
    params = strip_meta(message, params)
    if method == "notifications/initialized":
        if "id" in message or params:
            raise Denied("invalid initialized notification")
        return method
    if type(message.get("id")) not in (str, int):
        raise Denied("request id required; tool notifications are forbidden")
    if method == "initialize":
        if set(params) != {"protocolVersion", "capabilities", "clientInfo"}:
            raise Denied("invalid initialization")
        if (not isinstance(params["protocolVersion"], str) or not isinstance(params["capabilities"], dict)
                or not isinstance(params["clientInfo"], dict)):
            raise Denied("invalid initialization")
    elif method == "ping":
        if params:
            raise Denied("invalid ping")
    elif method == "tools/list":
        if set(params) - {"cursor"} or ("cursor" in params and not isinstance(params["cursor"], str)):
            raise Denied("invalid list")
    elif method == "tools/call":
        name = params.get("name")
        if set(params) - {"name", "arguments"} or not isinstance(name, str):
            raise Denied("tool not permitted")  # malformed: stays HTTP 403
        # 0.1.14: the four refusals of a well-formed call are ToolCallRefused (answered as JSON-RPC errors).
        if not enabled(name, tools, state):
            raise ToolCallRefused("unknown_tool", name)
        if tools[name].child_schema:
            child_call(name, tools[name], params, state, tools)
            return method
        model = tools[name].arguments
        try:
            arguments = model.model_validate(params.get("arguments", {}))
        except ValidationError as error:
            raise ToolCallRefused("invalid_params", name, argument_errors(model, error, params.get("arguments"))) from None
        normalized = arguments.model_dump(mode="json")
        tool = tools[name]
        check_operation_denies(name, tool, normalized, state)
        if tool.selector and normalized.get(tool.selector) in tool.write_operations:
            if f'{name}:{normalized[tool.selector]}' not in getattr(state, 'enabled_write_tools', ()):
                raise ToolCallRefused("operation_not_permitted", name)
        if tool.requires_backend or (tool.selector and normalized.get(tool.selector) in tool.backend_required_operations):
            configured = getattr(state, 'configured', bool(state.backend_url and state.backend_key))
            if not configured:
                raise ToolCallRefused("backend_not_configured", name)
        params["arguments"] = normalized
    else:  # unreachable: every other method is UnknownMethod above
        raise Denied("method not permitted")
    return method


def child_call(name, tool, params, state, tools):
    """A full-surface tool's child validates arguments and answers its own errors.

    Arguments must be a JSON object (or absent). n8n calls first
    normalize their reviewed wrapper/boolean forms, idempotently; other child
    arguments are forwarded unchanged.
    """
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ToolCallRefused("invalid_params", name, [{"field": "arguments", "message": "Input should be a valid dictionary",
                                                        "type": "dict_type"}])
    if tool.n8n_arguments:
        from .n8n_arguments import normalize
        try:
            arguments = normalize(name, arguments)
        except ValueError:
            raise ToolCallRefused('invalid_params', name, [{
                'field': 'arguments', 'message': 'Use one unambiguous argument object',
                'type': 'value_error'}]) from None
        params['arguments'] = arguments
    if (tool.exposure_write_tool and arguments.get('exposeToMcp') is True
            and not policy_enabled(tool.exposure_write_tool, tools, state)):
        raise ToolCallRefused('operation_not_permitted', name,
            reason='exposeToMcp requires the enabled n8n_update_partial_workflow write grant')
    check_operation_denies(name, tool, arguments, state)
    if tool.write_operations:
        granted = getattr(state, "enabled_write_tools", ())
        operation = arguments.get(tool.selector, tool.default_operation)
        if operation in tool.write_operations:
            needed = [operation]
        elif operation is None or type(operation) is str and operation in tool.read_operations:
            needed = []  # a read, or a required selector left out (the child refuses the call)
        else:  # not a string or a value this add-on has not classified: it could be a new write
            needed = list(tool.write_operations)
        if any(f"{name}:{value}" not in granted for value in needed):
            raise ToolCallRefused("operation_not_permitted", name)


# The four MCP hint annotations and their cautious values. A client may relax its own checks on the other value (Claude
# Code treats readOnlyHint as read-only and concurrency-safe), so that value is listed only for a tool with no local
# write path: the reviewed local Tool decides, never the child (0.1.6 R1 #1).
CAUTIOUS_HINTS = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}

# 0.1.6 (AI Stage 0, owner decision D21): Claude and GPT refuse a WHOLE request (HTTP 400) when any tool's input schema
# has one of these at its top level (Claude: oneOf/anyOf/allOf; OpenAI: also enum/const/not, and type must be "object");
# if, then and else mean nothing there without them. Nested uses are accepted. A top-level $ref is resolved too.
TOP_LEVEL_REFUSED = frozenset({"oneOf", "anyOf", "allOf", "enum", "const", "not", "if", "then", "else"})
RULES_PREFIX = "Argument rules (checked by the server): "


def declared_schema(arguments):
    """The inputSchema a tools/list declares for a local argument model; authorize() still validates with the model."""
    return flat_schema(arguments.model_json_schema())


def flat_schema(schema):
    """`schema` itself when its top level is {"type": "object"} without TOP_LEVEL_REFUSED keywords or $ref. Otherwise a
    SUPERSET with such a top level: the schema's own members (title, description, defaults, properties...) are kept,
    its combinators are replaced by what every instance they accept must satisfy (_object_view: required members, and
    members the schema itself does not declare), and their rules are appended to the description as plain clauses. The
    $defs still referenced are kept. Nothing the pinned model refuses is dispatched: authorize() validates with it."""
    if schema.get("type") == "object" and not (TOP_LEVEL_REFUSED | {"$ref"}) & schema.keys():
        return schema
    defs = schema["$defs"] if isinstance(schema.get("$defs"), dict) else {}
    # unevaluated* would no longer see what the removed branches evaluated: dropped (pydantic emits none).
    dropped = TOP_LEVEL_REFUSED | {"$ref", "discriminator", "unevaluatedProperties", "unevaluatedItems"}
    flat = {key: value for key, value in schema.items() if key not in dropped}
    properties, required, closed = _object_view(schema, defs)
    flat.update(type="object", properties=properties)
    if required:
        flat["required"] = required
    if closed and "additionalProperties" not in flat:
        flat["additionalProperties"] = False
    # Clauses name members in the schema's own order (pydantic's field order), then alphabetically: never in the order
    # of a branch, which a generator may build from a set (n8n_b3.folder_schema; the order then changes per process).
    order = list(schema["properties"]) if isinstance(schema.get("properties"), dict) else []
    rules = _rules(schema, defs, frozenset(), order)
    if rules:
        text = RULES_PREFIX + "; ".join(rules) + "."
        own = flat.get("description")
        flat["description"] = own + " " + text if isinstance(own, str) and own else text
    used = _used_defs({key: value for key, value in flat.items() if key != "$defs"}, defs)
    if used:
        flat["$defs"] = {name: value for name, value in defs.items() if name in used}
    else:
        flat.pop("$defs", None)
    return flat


def _object_view(schema, defs, seen=frozenset()):
    """(properties, required, closed) that every object `schema` accepts satisfies: an over-approximation. The schema's
    own properties win over those its combinators add (it is a conjunct of them, so its own are always checked); closed
    means additionalProperties false without patternProperties."""
    if not isinstance(schema, dict):
        return {}, [], False
    properties = dict(schema["properties"]) if isinstance(schema.get("properties"), dict) else {}
    required = [name for name in _listed(schema.get("required")) if isinstance(name, str)]
    closed = _closed(schema)
    views = [_object_view(member, defs, seen) for member in _listed(schema.get("allOf"))]  # all of them hold
    ref = _def_name(schema.get("$ref"))
    if ref in defs and ref not in seen:
        views.append(_object_view(defs[ref], defs, seen | {ref}))
    for key in ("oneOf", "anyOf"):
        if isinstance(schema.get(key), list):
            views.append(_union([_object_view(branch, defs, seen) for branch in schema[key] if branch is not False]))
    if "if" in schema and "then" in schema and "else" in schema:  # one of then/else holds; then alone may not
        views.append(_union([_object_view(schema["then"], defs, seen), _object_view(schema["else"], defs, seen)]))
    for other_properties, other_required, other_closed in views:
        for name, value in other_properties.items():
            if name not in properties and not closed:
                properties[name] = value
        required += [name for name in other_required if name not in required]
        closed = closed or other_closed  # properties then lists every member name the other view allows
    return properties, required, closed


def _closed(schema):
    return (isinstance(schema, dict) and schema.get("additionalProperties") is False
            and "patternProperties" not in schema)


def _union(views):
    """What every object accepted by one of `views` satisfies: the members every view requires; a member's schemas
    merged (_any_of) unless a view leaves it free; closed only if every view is."""
    if not views:
        return {}, [], False
    required = [name for name in views[0][1] if all(name in view[1] for view in views[1:])]
    properties = {}
    for name in dict.fromkeys(name for view in views for name in view[0]):
        # A false member schema only forbids the member: left out, as where a view leaves it free.
        schemas = [view[0][name] for view in views if name in view[0] and view[0][name] is not False]
        if not schemas or any(name not in view[0] and not view[2] for view in views):
            continue
        properties[name] = {} if any(schema is True or schema == {} for schema in schemas) else _any_of(schemas)
    return properties, required, all(view[2] for view in views)


def _any_of(schemas):
    """A schema accepting what any of `schemas` accepts: identical schemas kept once, string const/enum values merged
    into one enum, otherwise a nested anyOf of the distinct schemas."""
    distinct = []
    for schema in schemas:
        if all(_canonical(schema) != _canonical(kept) for kept in distinct):
            distinct.append(schema)
    literals = [schema for schema in distinct if _strings(schema) is not None]
    if len(literals) > 1:
        values = []
        for schema in literals:
            values += [value for value in _strings(schema) if value not in values]
        first = next(index for index, schema in enumerate(distinct) if schema is literals[0])
        distinct = [schema for schema in distinct if not any(schema is literal for literal in literals)]
        distinct.insert(first, {"type": "string", "enum": values})
    return distinct[0] if len(distinct) == 1 else {"anyOf": distinct}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _strings(schema):
    """The values of a string const or enum schema (optionally typed and titled), else None. A type other than string
    matches none of the values: merging such a schema only widens what accepted nothing."""
    if (not isinstance(schema, dict) or set(schema) - {"const", "enum", "type", "title", "description"}
            or ("const" in schema) == ("enum" in schema)):
        return None
    values = [schema["const"]] if "const" in schema else schema["enum"]
    return values if isinstance(values, list) and values and all(isinstance(v, str) for v in values) else None


def _def_name(ref):
    return ref[len("#/$defs/"):].split("/")[0] if isinstance(ref, str) and ref.startswith("#/$defs/") else None


def _used_defs(value, defs):
    """The $defs `value` references, directly or through other $defs."""
    used, todo = set(), [value]
    while todo:
        item = todo.pop()
        if isinstance(item, dict):
            name = _def_name(item.get("$ref"))
            if name in defs and name not in used:
                used.add(name)
                todo.append(defs[name])
            todo += list(item.values())
        elif isinstance(item, list):
            todo += item
    return used


def _rules(schema, defs, seen, order):
    """Clauses for the rules of `schema`'s top-level combinators, which the declared form no longer carries."""
    if not isinstance(schema, dict):
        return []
    rules = []
    for member in _listed(schema.get("allOf")):
        rules += _clauses(member, order=order) + _rules(member, defs, seen, order)
    ref = _def_name(schema.get("$ref"))
    if ref in defs and ref not in seen:
        rules += _rules(defs[ref], defs, seen | {ref}, order)
    for key in ("oneOf", "anyOf"):
        if isinstance(schema.get(key), list):
            rules.append(_branch_rules([branch for branch in schema[key] if branch is not False], defs, order))
    if "if" in schema and ("then" in schema or "else" in schema):
        then, other = (", ".join(_clauses(schema.get(key), order=order)) for key in ("then", "else"))
        rules.append("if " + _condition(schema["if"], order) + ": " + (then or "no further rules")
                     + ("; otherwise: " + (other or "no further rules") if "else" in schema else ""))
    if "not" in schema:
        rules.append("the arguments must not match " + _compact(schema["not"]))
    if "const" in schema:
        rules.append("the arguments must equal " + _compact(schema["const"]))
    if isinstance(schema.get("enum"), list):
        rules.append("the arguments must be one of " + _compact(schema["enum"]))
    return [rule for rule in rules if rule]


def _branch_rules(branches, defs, order):
    """One clause list per branch, labelled by the member whose string values tell the branches apart, if any."""
    if not branches:
        return ""
    branches = [defs.get(_def_name(branch.get("$ref")), branch) if isinstance(branch, dict) else branch
                for branch in branches]
    members = [branch.get("properties") if isinstance(branch, dict) and isinstance(branch.get("properties"), dict)
               else {} for branch in branches]
    key = next((name for name in _sorted(members[0], order) if len(branches) > 1
                and all(_strings(m.get(name)) for m in members)
                and len({v for m in members for v in _strings(m[name])})
                == sum(len(_strings(m[name])) for m in members)), None)
    names = _sorted(dict.fromkeys(name for member in members for name in member), order)
    parts = []
    for branch, member in zip(branches, members):
        absent = [name for name in names if name not in member] if _closed(branch) else []  # declared by others only
        clauses = ", ".join(_clauses(branch, skip=key, absent=absent, order=order)) or "no further rules"
        if key is None:
            parts.append(f"({len(parts) + 1}) {clauses}")
            continue
        values = _strings(member[key])
        label = key + "=" + _compact(values[0]) if len(values) == 1 else key + " one of " + _compact(values)
        omittable = isinstance(branch, dict) and key not in _listed(branch.get("required"))
        parts.append(label + (" (or omitted)" if omittable else "") + ": " + clauses)
    return "; ".join(parts) if key is not None else "the arguments must match one of: " + "; ".join(parts)


def _clauses(schema, skip=None, prefix="", absent=(), order=()):
    """Plain clauses for what `schema` asks of an object's members: required, to omit (null-only or false, and the
    `absent` names), fixed or excluded values; members in `order`, then by name; nested members as dotted paths. Other
    keywords are left to the member schemas and the server."""
    if not isinstance(schema, dict):
        return []
    properties = schema["properties"] if isinstance(schema.get("properties"), dict) else {}
    required = [name for name in _listed(schema.get("required")) if isinstance(name, str) and name != skip]
    names = [name for name in _sorted(properties, order) if name != skip]
    needs = [prefix + name for name in _sorted(dict.fromkeys(required), order) if not _omitted(properties.get(name))]
    omits = [prefix + name for name in _sorted(dict.fromkeys(
        [name for name in names if name not in required and _omitted(properties[name])] + list(absent)), order)]
    clauses = (["requires " + _names(needs)] if needs else []) + (["omit " + _names(omits)] if omits else [])
    for name in names:
        sub = properties[name]
        if not isinstance(sub, dict):
            continue
        path = prefix + name
        if name in required and _omitted(sub):
            clauses.append(path + " must be null")
        values = [sub["const"]] if "const" in sub else _listed(sub.get("enum"))
        if values:
            clauses.append(path + (" must be " + _compact(values[0]) if len(values) == 1
                                   else " must be one of " + ", ".join(map(_compact, values))))
        excluded = _excluded(sub.get("not"))
        if excluded:
            clauses.append(path + " must not be " + " or ".join(map(_compact, excluded)))
        if isinstance(sub.get("properties"), dict) or sub.get("required"):
            clauses += _clauses(sub, prefix=path + ".")
    return clauses


def _omitted(schema):
    return schema is False or isinstance(schema, dict) and schema.get("type") == "null" and not (
        set(schema) - {"type", "title", "description", "default"})


def _excluded(schema):
    """The values a `not` schema names (const, enum, or such members of anyOf/oneOf); patterns are left as they are."""
    if not isinstance(schema, dict):
        return []
    values = [schema["const"]] if "const" in schema else list(_listed(schema.get("enum")))
    for key in ("anyOf", "oneOf"):
        for member in _listed(schema.get(key)):
            if isinstance(member, dict):
                values += _excluded({k: v for k, v in member.items() if k in ("const", "enum")})
    return values


def _condition(schema, order):
    """An `if` schema as `member="value"` terms when it only fixes member values (or asks for members), else as JSON."""
    members = schema.get("properties") if isinstance(schema, dict) else None
    if (isinstance(members, dict) and not set(schema) - {"properties", "required"}
            and all(isinstance(sub, dict) and ("const" in sub or isinstance(sub.get("enum"), list))
                    and not set(sub) - {"const", "enum", "type", "title", "description"} for sub in members.values())):
        parts = [name + ("=" + _compact(members[name]["const"]) if "const" in members[name]
                         else " is one of " + _compact(members[name]["enum"])) for name in _sorted(members, order)]
        parts += [name + " is present" for name in _sorted(dict.fromkeys(_listed(schema.get("required"))), order)]
        if parts:
            return " and ".join(parts)
    return "the arguments match " + _compact(schema)


def _sorted(names, order):
    order = list(order)
    return sorted(names, key=lambda name: (order.index(name) if name in order else len(order), name))


def _listed(value):
    return value if isinstance(value, list) else []


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _names(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def child_input_schema(schema):
    """0.2.0: the child's own inputSchema, made provider-safe like a local one (flat_schema: a top-level object without
    oneOf/anyOf/allOf/enum/const/not/$ref, which Claude and GPT refuse for a whole request). A schema that is not an
    object, or that flat_schema cannot read, is listed as a plain object: the child still validates every call."""
    if not isinstance(schema, dict):
        return {"type": "object"}
    try:
        flat = flat_schema(schema)
        json.dumps(flat)
    except Exception:
        return {"type": "object"}
    return flat


def listed_tool(tool, local):
    """A listed tool rebuilt from known members (0.1.6, 0.1.5 RC review F3). The name and inputSchema are the gateway's
    own (0.1.6 AI Stage 0: the declared form of the locally pinned argument model, declared_schema()); title,
    description and annotations.title are the child's text, kept only as strings; the four hint booleans are kept when
    cautious, or when the local tool has no write path. outputSchema, execution, icons, _meta and unknown members are
    dropped: the pinned TS client compiles a child's outputSchema (a $ref or pattern then becomes its error text, and
    the Python client fetched a child $ref URL) and refuses every call to a tool whose execution.taskSupport is
    "required"; icons are child-chosen URLs."""
    read_only = not (local.write or local.legacy_write or local.write_operations)
    listed = {"name": tool["name"], "inputSchema": child_input_schema(tool.get("inputSchema")) if local.child_schema
              else declared_schema(local.arguments)}
    listed.update({key: tool[key] for key in ("title", "description") if isinstance(tool.get(key), str)})
    annotations = tool.get("annotations")
    if isinstance(annotations, dict):
        kept = {"title": annotations["title"]} if isinstance(annotations.get("title"), str) else {}
        for key, cautious in CAUTIOUS_HINTS.items():
            value = annotations.get(key)
            if type(value) is bool and (value is cautious or read_only):
                kept[key] = value
        if kept:
            listed["annotations"] = kept
    return listed


def filter_list(message, tools: Mapping[str, Tool], state: State):
    if not isinstance(message, dict):
        raise ValueError("invalid list response")
    result = message.get("result")
    if isinstance(result, dict) and "tools" in result:
        if not isinstance(result["tools"], list):
            raise ValueError("invalid tools response")
        listed, names = [], set()
        for tool in result["tools"]:
            # The first entry per name only (0.1.6 R1 #5): LLM providers refuse duplicate function names.
            if (isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"] not in names
                    and policy_enabled(tool["name"], tools, state)):
                names.add(tool["name"])
                listed.append(listed_tool(tool, tools[tool["name"]]))
        # The result is rebuilt as well (0.1.6 R1 #4): the tools and a string nextCursor, nothing else from the child.
        message["result"] = result = {"tools": listed, **({"nextCursor": result["nextCursor"]}
                                                          if isinstance(result.get("nextCursor"), str) else {})}
    # Also applies to resumed SSE replies: no unsupported capabilities or
    # listChanged promise may escape the method allowlist at the boundary.
    if isinstance(result, dict) and "capabilities" in result:
        result["capabilities"] = {"tools": {}}
    return message
