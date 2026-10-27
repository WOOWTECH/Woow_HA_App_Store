"""Root-owned, bounded Supervisor metadata lookup; stdout contains no secrets."""
import json
import os
import re
import signal
import urllib.request

SELF_INFO = 'http://supervisor/addons/self/info'
MAX_RESPONSE_BYTES = 131072
FALLBACK = ('/', '← 返回 Home Assistant')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def return_target(token, *, endpoint=SELF_INFO, deadline=3):
    # endpoint/deadline are injectable only for local HTTP tests. The production
    # entrypoint always uses SELF_INFO; no environment or CLI endpoint override.
    if not token:
        return FALLBACK

    def expired(_signal, _frame):
        raise TimeoutError()

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, deadline)
    try:
        # Never send this credential through an ambient proxy or redirect.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(endpoint, headers={'Authorization': 'Bearer ' + token})
        with opener.open(request, timeout=deadline) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return FALLBACK
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('result') != 'ok':
            return FALLBACK
        data = value.get('data')
        slug = data.get('slug') if isinstance(data, dict) else None
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', slug):
            return FALLBACK
        return '/app/' + slug, '← 返回 OpenDesign'
    except Exception:
        # Exception strings and response bodies may contain credentials/options.
        return FALLBACK
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def nginx_config(target):
    path, label = target
    return f'set $ha_return_path "{path}";\nset $ha_return_label "{label}";\n'


def main():
    try:
        target = return_target(os.environ.get('SUPERVISOR_TOKEN') or os.environ.get('HASSIO_TOKEN', ''))
    except Exception:
        target = FALLBACK
    print(nginx_config(target), end='')


if __name__ == '__main__':
    main()
