"""Configured-backend transports only; no global resolver/socket/SSRF changes.

Address classes mirror apps/n8n/backend_policy.cjs + pinned ipaddr.js 1.9.1.
HTTPX/httpcore internals are pinned by each child lock (0.28.1/1.0.9).
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import hashlib
import inspect
import http.client
from pathlib import Path
import ipaddress
import socket
import ssl
import threading
import time
import xmlrpc.client
from urllib.parse import unquote, urlsplit

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.sync import SyncStream


# Private pool integration is reviewed only for these exact locked sources.
_SOURCE_HASHES = {
    'httpx/_transports/default.py': '03379a454c95c0271c4f2c8d25ec437f49f57457f3cf2769748420bf0ecf2e79',
    'httpcore/_async/connection_pool.py': '0ce210dacd9909ff6a7f0c61ccca6b4cf2ea08bf0ec465e2285eaa447c6f5726',
    'httpcore/_async/connection.py': 'e8e70f5ea3047dcd01537f3ffa21d4343775bca4937365154f4f57a8d6ff04e9',
    'httpcore/_sync/connection_pool.py': '6be4fc2d3b14c5ceebd16c356ad7c7483a163e34347c0f1497b4b7f85d0c8fbd',
    'httpcore/_sync/connection.py': 'f5ec4639bdcf07e329d93d7eb1c91278bdadfad27ff7e357a2657c8a19960a05',
    'httpcore/_backends/anyio.py': 'c7c3e01215d10bc6d5aac77393f609c7c63a77d4ee6f4e82b944b09db9adaa86',
    'httpcore/_backends/sync.py': '6e113877d88af549b176c76c826d847ca9d76819acd9682019853eee3994ba35',
}


def check_sources():
    for relative, expected in _SOURCE_HASHES.items():
        module = httpx if relative.startswith('httpx/') else httpcore
        path = Path(module.__file__).parent.parent / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('HTTP backend transport requires source review')


check_sources()


class BackendHTTPError(httpx.HTTPError):
    def __init__(self, status):
        self.status = int(status)
        super().__init__(f'BACKEND_HTTP_ERROR status={self.status}')


class BackendBusy(httpx.HTTPError):
    def __init__(self):
        super().__init__('BACKEND_BUSY')


# One executor/admission gate per child process, shared by ALL client instances
# and sync/async/XMLRPC paths. No admission queue. A request's timeout/cancellation
# cannot release a running resolver's slot. Non-daemon executor threads are owned
# until real completion; Supervisor's process-group deadline reaps hung workers.
RESOLVER_CAPACITY = 4
_RESOLVER_SLOTS = threading.BoundedSemaphore(RESOLVER_CAPACITY)
_RESOLVERS = ThreadPoolExecutor(max_workers=RESOLVER_CAPACITY, thread_name_prefix='backend-dns')


class BackendDenied(ValueError):
    def __init__(self):
        super().__init__('BACKEND_DESTINATION_DENIED')


class BackendStreamError(httpx.HTTPError):
    def __init__(self):
        super().__init__('BACKEND_STREAM_ERROR')


def public_backend_error(exc):
    """Type-based public error mapping. Never inspect backend exception text."""
    if isinstance(exc, BackendFailure):
        return exc.code
    if isinstance(exc, BackendHTTPError):
        return f'BACKEND_HTTP_ERROR status={exc.status}'
    if isinstance(exc, BackendBusy):
        return 'BACKEND_BUSY'
    if isinstance(exc, BackendDenied):
        return 'BACKEND_DESTINATION_DENIED'
    if isinstance(exc, (httpx.TimeoutException, httpcore.TimeoutException, TimeoutError)):
        return 'BACKEND_TIMEOUT'
    if isinstance(exc, BackendStreamError):
        return 'BACKEND_STREAM_ERROR'
    if isinstance(exc, (httpx.DecodingError, UnicodeError, ValueError)):
        return 'BACKEND_INVALID_RESPONSE'
    return 'BACKEND_UNAVAILABLE'


class BackendFailure(httpx.HTTPError):
    def __init__(self, exc):
        self.code = public_backend_error(exc)
        super().__init__(self.code)


def backend_errors(function):
    """Explicit enabled-handler boundary, including decoding after stream reads.

    Preserve signatures/async dispatch and successful business values unchanged.
    Exception only: cancellation, GeneratorExit and process signals propagate.
    """
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def async_call(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except Exception as exc:
                raise BackendFailure(exc) from None
        return async_call

    @wraps(function)
    def sync_call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            raise BackendFailure(exc) from None
    return sync_call


_V4_DENY = tuple(map(ipaddress.ip_network, (
    '0.0.0.0/8', '169.254.0.0/16', '100.64.0.0/10', '224.0.0.0/4',
    '192.0.0.0/24', '192.0.2.0/24', '192.88.99.0/24', '198.51.100.0/24',
    '203.0.113.0/24', '240.0.0.0/4', '168.63.129.16/32')))
_V6_DENY = tuple(map(ipaddress.ip_network, ('2002::/16', '2001::/32', '2001:db8::/32', 'fd00:ec2::254/128')))


def allowed_address(value):
    try:
        if '%' in value:
            return False
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.version == 4:
        return not any(ip in network for network in _V4_DENY)
    return (ip == ipaddress.ip_address('::1') or ip in ipaddress.ip_network('fc00::/7') or
            ip in ipaddress.ip_network('2000::/3')) and not any(ip in network for network in _V6_DENY)


def checked_answers(host, port):
    """Resolve once, validate ALL answers before any connect, return numeric tuples."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    else:
        family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
        answers = [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (str(ip), port))]
    if not answers:
        raise BackendDenied()
    result = []
    for family, kind, proto, _, address in answers:
        if (family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM or
                proto != socket.IPPROTO_TCP or not allowed_address(address[0]) or
                ipaddress.ip_address(address[0]).version != (4 if family == socket.AF_INET else 6) or
                address[1] != port or (len(address) > 3 and address[3] != 0)):
            raise BackendDenied()
        result.append((family, address))
    return result


def path_value(path):
    path = unquote(path)
    if '%' in path or '\\' in path or any(p in ('.', '..') for p in path.split('/')):
        raise BackendDenied()
    return path.rstrip('/') or '/'


class Destination:
    def __init__(self, base_url):
        url = urlsplit(str(base_url))
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise BackendDenied()
        self.scheme, self.host = url.scheme, url.hostname.lower()
        self.port = url.port or (443 if self.scheme == 'https' else 80)
        self.path = path_value(url.path)
        if self.host.rstrip('.') in ('metadata', 'metadata.google.internal', 'instance-data'):
            raise BackendDenied()

    def check_host(self, host, port):
        if host.lower() != self.host or port != self.port:
            raise BackendDenied()

    def check_url(self, value):
        url = urlsplit(str(value))
        self.check_host(url.hostname or '', url.port or (443 if url.scheme == 'https' else 80))
        path = path_value(url.path)
        if (url.scheme != self.scheme or url.username or url.password or url.fragment or
                not (self.path == '/' or path == self.path or path.startswith(self.path + '/'))):
            raise BackendDenied()


def connection_deadline(timeout):
    # Even callers disabling HTTPX timeouts get a finite DNS/TCP budget.
    return time.monotonic() + (5.0 if timeout is None else timeout)


def remaining(deadline):
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise TimeoutError('BACKEND_TIMEOUT')
    return budget


def resolve_future(host, port):
    if not _RESOLVER_SLOTS.acquire(blocking=False):
        raise BackendBusy()
    try:
        future = _RESOLVERS.submit(checked_answers, host, port)
    except BaseException:
        _RESOLVER_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _RESOLVER_SLOTS.release())
    return future


def resolve_sync(host, port, deadline):
    budget = remaining(deadline)
    # result(timeout) never cancels the underlying concurrent future.
    return resolve_future(host, port).result(timeout=budget)


async def resolve_async(host, port, deadline):
    budget = remaining(deadline)
    future = asyncio.wrap_future(resolve_future(host, port))
    # Observe late exceptions, but never detach execution ownership or cancel the
    # concurrent future when a caller leaves. Its done callback owns admission.
    future.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    return await asyncio.wait_for(asyncio.shield(future), timeout=budget)


def connect_socket(answers, timeout, deadline):
    # Entire answer set is already validated. Divide the remaining budget among
    # remaining candidates so a blackholed first address cannot starve fallback.
    # No socket.create_connection/getaddrinfo second lookup, including literals.
    for index, (family, address) in enumerate(answers):
        budget = remaining(deadline) / (len(answers) - index)
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(budget)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect(address)
            sock.settimeout(timeout)  # restore ordinary I/O timeout for XMLRPC
            return sock
        except OSError:
            if sock is not None:
                sock.close()
            if index == len(answers) - 1:
                raise
        except BaseException:
            if sock is not None:
                sock.close()
            raise


class PinnedSyncBackend(httpcore.NetworkBackend):
    def __init__(self, destination):
        self.destination = destination

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.destination.check_host(host, port)
        deadline = connection_deadline(timeout)
        try:
            answers = resolve_sync(host, port, deadline)
            return SyncStream(connect_socket(answers, timeout, deadline))
        except TimeoutError:
            raise httpcore.ConnectTimeout('BACKEND_TIMEOUT') from None
        except OSError:
            raise httpcore.ConnectError('BACKEND_CONNECT_FAILED') from None


class PinnedAsyncBackend(AnyIOBackend):
    def __init__(self, destination):
        self.destination = destination

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.destination.check_host(host, port)
        deadline = connection_deadline(timeout)
        try:
            answers = await resolve_async(host, port, deadline)
            for index, (_, address) in enumerate(answers):
                budget = remaining(deadline) / (len(answers) - index)
                try:
                    # AnyIO receives only a validated numeric IP, never hostname.
                    return await super().connect_tcp(address[0], port, budget, None, socket_options)
                except (httpcore.ConnectError, httpcore.ConnectTimeout):
                    if index == len(answers) - 1:
                        raise
        except TimeoutError:
            raise httpcore.ConnectTimeout('BACKEND_TIMEOUT') from None


class SyncResponseStream(httpx.SyncByteStream):
    """Lazy pass-through; HTTPX/core retain response and connection ownership."""
    def __init__(self, stream):
        self.stream = stream

    def __iter__(self):
        try:
            yield from self.stream
        except (httpx.TimeoutException, httpcore.TimeoutException):
            raise httpx.TimeoutException('BACKEND_TIMEOUT') from None
        except Exception:
            raise BackendStreamError() from None

    def close(self):
        try:
            self.stream.close()
        except (httpx.TimeoutException, httpcore.TimeoutException):
            raise httpx.TimeoutException('BACKEND_TIMEOUT') from None
        except Exception:
            raise BackendStreamError() from None


class AsyncResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        try:
            async for chunk in self.stream:
                yield chunk
        except (httpx.TimeoutException, httpcore.TimeoutException):
            raise httpx.TimeoutException('BACKEND_TIMEOUT') from None
        except Exception:
            raise BackendStreamError() from None

    async def aclose(self):
        try:
            await self.stream.aclose()
        except (httpx.TimeoutException, httpcore.TimeoutException):
            raise httpx.TimeoutException('BACKEND_TIMEOUT') from None
        except Exception:
            raise BackendStreamError() from None


class SyncTransport(httpx.HTTPTransport):
    def __init__(self, base_url):
        self.destination = Destination(base_url)
        super().__init__(trust_env=False, limits=httpx.Limits(max_connections=4, max_keepalive_connections=0))
        self._pool._network_backend = PinnedSyncBackend(self.destination)

    def handle_request(self, request):
        self.destination.check_url(request.url)
        if 'sni_hostname' in request.extensions:
            raise BackendDenied()
        try:
            response = super().handle_request(request)
        except (BackendDenied, BackendBusy):
            raise
        except httpx.TimeoutException:
            raise httpx.TimeoutException('BACKEND_TIMEOUT') from None
        except Exception:
            raise httpx.ConnectError('BACKEND_UNAVAILABLE') from None
        response.stream = SyncResponseStream(response.stream)
        if not 200 <= response.status_code < 300:
            try:
                response.close()
            except Exception:
                pass  # Status is authoritative; cleanup diagnostics are not public.
            raise BackendHTTPError(response.status_code)
        return response


class AsyncTransport(httpx.AsyncHTTPTransport):
    def __init__(self, base_url):
        self.destination = Destination(base_url)
        super().__init__(trust_env=False, limits=httpx.Limits(max_connections=4, max_keepalive_connections=0))
        self._pool._network_backend = PinnedAsyncBackend(self.destination)

    async def handle_async_request(self, request):
        self.destination.check_url(request.url)
        if 'sni_hostname' in request.extensions:
            raise BackendDenied()
        try:
            response = await super().handle_async_request(request)
        except (BackendDenied, BackendBusy):
            raise
        except httpx.TimeoutException:
            raise httpx.TimeoutException('BACKEND_TIMEOUT') from None
        except Exception:
            raise httpx.ConnectError('BACKEND_UNAVAILABLE') from None
        response.stream = AsyncResponseStream(response.stream)
        if not 200 <= response.status_code < 300:
            try:
                await response.aclose()
            except Exception:
                pass  # Do not swallow cancellation or replace the status error.
            raise BackendHTTPError(response.status_code)
        return response


def sync_client(*, base_url, **kwargs):
    kwargs.pop('limits', None)
    return httpx.Client(base_url=base_url, transport=SyncTransport(base_url),
                        trust_env=False, follow_redirects=False, **kwargs)


def async_client(*, base_url, **kwargs):
    kwargs.pop('limits', None)
    return httpx.AsyncClient(base_url=base_url, transport=AsyncTransport(base_url),
                             trust_env=False, follow_redirects=False, **kwargs)


class PinnedHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        if self._tunnel_host:
            raise BackendDenied()
        deadline = connection_deadline(self.timeout)
        self.sock = connect_socket(resolve_sync(self.host, self.port, deadline), self.timeout, deadline)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._tunnel_host or not self._context.check_hostname or self._context.verify_mode != ssl.CERT_REQUIRED:
            raise BackendDenied()
        deadline = connection_deadline(self.timeout)
        sock = connect_socket(resolve_sync(self.host, self.port, deadline), self.timeout, deadline)
        try:
            # Original hostname, never the pinned address: SNI + certificate identity.
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class XMLTransport(xmlrpc.client.Transport):
    def __init__(self, base_url, *, timeout=5, database=None):
        super().__init__()
        self.destination = Destination(base_url)
        self.timeout, self.database = timeout, database

    def make_connection(self, host):
        url = urlsplit(f'{self.destination.scheme}://{host}')
        self.destination.check_host(url.hostname or '', url.port or (443 if url.scheme == 'https' else 80))
        cls = PinnedHTTPSConnection if self.destination.scheme == 'https' else PinnedHTTPConnection
        connection = cls(host, timeout=self.timeout)
        self._connection = (host, connection)
        return connection

    def send_headers(self, connection, headers):
        super().send_headers(connection, headers)
        if self.database:
            connection.putheader('X-Odoo-Database', self.database)

    def request(self, host, handler, request_body, verbose=False):
        self.destination.check_url(f'{self.destination.scheme}://{host}{handler}')
        # No redirect following (including relative/same origin), no unbounded retry.
        try:
            return self.single_request(host, handler, request_body, verbose)
        except (BackendDenied, BackendBusy):
            raise
        except TimeoutError:
            raise ValueError('BACKEND_TIMEOUT') from None
        except xmlrpc.client.ProtocolError as exc:
            raise ValueError(f'BACKEND_HTTP_ERROR status={int(exc.errcode)}') from None
        except xmlrpc.client.Fault:
            raise ValueError('BACKEND_RPC_FAULT') from None
        except Exception:
            raise ValueError('BACKEND_UNAVAILABLE') from None
        finally:
            self.close()
