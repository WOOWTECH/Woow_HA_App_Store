"""Bounded positive output projections for newly enabled metadata operations.

Unknown/nested fields never survive. This is not a key-name denylist and does
not claim to sanitize arbitrary chat, files, prompts or provider configuration.
"""

def rows(body, key, fields):
    values = body.get(key) if isinstance(body, dict) else body
    if not isinstance(values, list):
        raise ValueError('unexpected metadata envelope')
    return {key: [record(row, fields) for row in values[:100]], 'truncated': len(values) > 100}


def record(body, fields):
    if not isinstance(body, dict):
        raise ValueError('unexpected metadata record')
    result = {}
    for key in fields:
        value = body.get(key)
        if value is None or type(value) in (bool, int, float):
            result[key] = value
        elif type(value) is str:
            result[key] = value[:256]
    return result
