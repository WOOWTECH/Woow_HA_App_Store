"""Validate an administrator-configured HA Origin without logging its input."""
import sys
import re
from urllib.parse import urlsplit


def canonical_origin(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError('origin required')
    parsed = urlsplit(value)
    label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    authority = rf'(?:{label}(?:\.{label})*\.?|\[[0-9A-Fa-f:.]+\])(?::[0-9]+)?'
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or not re.fullmatch(authority, parsed.netloc)
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or any(c in value for c in ('*', '\\', '?', '#'))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('exact origin required')
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('invalid port')
    return value.rstrip('/')


if __name__ == '__main__':
    try:
        value = sys.stdin.read(4097)
        if len(value) > 4096:
            raise ValueError('origin too long')
        print(canonical_origin(value))
    except ValueError:
        sys.exit('Invalid paseo_ingress_url: use an exact http(s) Home Assistant origin, without credentials or a path.')
