"""Pinned n8n-mcp 2.91.0 argument boundary for its complete tool surface.

Match server.validateExtractedArgs and boolean coercion before authorizing and
forwarding. Never recursively unwrap: the child must see the same argument object
on its next preprocessing pass. Tests compare the actual pinned JS methods.
"""
import json
import re

from .tool_snapshot import LISTED

EXPOSURE_TOOLS = ('n8n_workflow_versions', 'n8n_test_workflow')
SCHEMAS = {tool['name']: tool['inputSchema'] for tool in LISTED['n8n']}
# ECMAScript String.trim whitespace; Python strip also removes some JS non-whitespace.
JS_WHITESPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
NUMBER = re.compile(r'(?:[+-]?(?:Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)|0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+)\Z')


def _type(value):
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict) or value is None:
        return 'object'  # JS typeof null; the child's Zod parser still validates it
    return {str: 'string', bool: 'boolean', int: 'number', float: 'number'}[type(value)]


def _valid_extracted(name, value):
    schema = SCHEMAS[name]
    if any(key not in value for key in schema.get('required', ())):
        return False
    for key, item in value.items():
        expected = schema.get('properties', {}).get(key, {}).get('type')
        actual = _type(item)
        if expected and expected != actual:
            # Pinned validator permits numeric strings only (not boolean strings).
            if expected == 'number' and actual == 'string':
                text = item.strip(JS_WHITESPACE)
                if not text or NUMBER.fullmatch(text):
                    continue
            return False
    # additionalProperties=false only logs upstream; it does not reject extraction.
    return True


def _reject_constant(_value):
    raise json.JSONDecodeError('invalid JSON constant', '', 0)


def _extracted(name, arguments):
    raw = arguments.get('output')
    if not isinstance(raw, str) or not raw.strip(JS_WHITESPACE).startswith('{'):
        return None
    try:
        value = json.loads(raw, parse_constant=_reject_constant)
    except json.JSONDecodeError:
        return None  # exactly the pinned child's fallback to the outer arguments
    except (ValueError, RecursionError):
        # Python's integer/depth limits can reject JSON that JS accepts. Never
        # forward a still-wrapped call when its effective arguments are unknown.
        raise ValueError('cannot safely inspect nested output') from None
    return value if isinstance(value, dict) and _valid_extracted(name, value) else None


def normalize(name, arguments):
    """One child-compatible unwrap; reject a second eligible unwrap, never widen grants.

    The n8n HTTP request limits already bound encoded bytes/elements/depth before
    policy. The original and normalized arguments remain inside that same budget.
    """
    inner = _extracted(name, arguments)
    if inner is not None:
        arguments = inner
        if _extracted(name, arguments) is not None:
            raise ValueError('ambiguous nested output')
    normalized = dict(arguments)
    flag = normalized.get('exposeToMcp')
    if name in EXPOSURE_TOOLS and isinstance(flag, str) and flag.strip(JS_WHITESPACE) in ('true', 'false'):
        normalized['exposeToMcp'] = flag.strip(JS_WHITESPACE) == 'true'
    return normalized
