"""Fail-closed LAN signup on a separately permissioned Unix proxy transport.

Forwarded headers and TCP peer addresses never grant enrollment authority. The
edge must overwrite the single client-address signal on the private Unix path.
"""
import asyncio
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import json
from pathlib import Path
import stat
from time import monotonic

import psycopg

from m2.archive.store import Store
from m2.http_boundary.boundary import Forbidden, json_body, json_response

CLIENT_HEADER = b'x-kat-signup-client'
FORWARDED = {b'forwarded', b'x-forwarded-for', b'x-forwarded-host', b'x-forwarded-proto', b'x-real-ip'}
SIGNUP_INTERVAL = 10


def address(value):
    if not isinstance(value, str) or value != value.strip() or '%' in value:
        raise ValueError('Invalid client address')
    parsed = ip_address(value)
    return getattr(parsed, 'ipv4_mapped', None) or parsed


@dataclass(frozen=True)
class SignupPolicy:
    socket: str
    networks: tuple
    excluded: tuple

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != {'socket', 'networks', 'excluded_clients'}:
            raise ValueError('Explicit signup socket, networks and excluded clients required')
        path = value['socket']
        if (not isinstance(path, str) or not Path(path).is_absolute() or '..' in Path(path).parts
                or len(path.encode()) > 100):
            raise ValueError('Invalid signup socket path')
        if any(not isinstance(value[key], list) or not 1 <= len(value[key]) <= 16
               for key in ('networks', 'excluded_clients')):
            raise ValueError('Bounded explicit home networks and router/proxy exclusions required')
        if any(not isinstance(item, str) for item in value['networks']):
            raise ValueError('Network entries must be explicit CIDR strings')
        networks = tuple(ip_network(item, strict=True) for item in value['networks'])
        if any(net.prefixlen < (16 if net.version == 4 else 48)
               or net.is_loopback or net.is_link_local or net.is_multicast
               or getattr(net.network_address, 'ipv4_mapped', None) for net in networks):
            raise ValueError('Use explicit home subnets, not broad or special address ranges')
        excluded = tuple(address(item) for item in value['excluded_clients'])
        return cls(path, networks, excluded)

    @classmethod
    def load(cls, path):
        path = Path(path)
        info = path.lstat()
        if (not path.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_size > 4096):
            raise ValueError('Signup policy must be an absolute root-owned non-writable regular file')
        return cls.parse(json.loads(path.read_text(encoding='utf-8')))

    def admits(self, request):
        # Uvicorn supplies the actual local Unix socket name and no TCP peer.
        # proxy_headers=False is mandatory; no HTTP header can set these fields.
        if request.scope.get('server') != (self.socket, None) or request.scope.get('client') is not None:
            return False
        headers = request.scope['headers']
        if any(key.lower() in FORWARDED or key.lower().startswith(b'x-forwarded-') for key, _ in headers):
            return False
        values = [value for key, value in headers if key.lower() == CLIENT_HEADER]
        if len(values) != 1:
            return False
        try:
            client = address(values[0].decode('ascii'))
        except (ValueError, UnicodeError):
            return False
        if (client in self.excluded or client.is_loopback or client.is_link_local
                or client.is_multicast or client.is_unspecified):
            return False
        return any(client in network and client != network.network_address
                   and (network.version != 4 or client != network.broadcast_address)
                   for network in self.networks)


class Signup:
    """One bounded hash job at a time, at most one admission every ten seconds.

    The same limit covers all LAN clients and duplicates; no per-IP cache grows.
    An HTTP disconnect cannot free the slot while its Store worker is still busy.
    """
    def __init__(self, policy=None, clock=monotonic):
        self.policy, self.clock = policy, clock
        self.next_attempt = 0
        self.pending = None

    def allowed(self, request):
        return self.policy is not None and self.policy.admits(request)

    async def create(self, runtime, username, password):
        if self.pending is not None or self.clock() < self.next_attempt:
            response = json_response({'error': 'signup_busy'}, 429)
            response.headers['Retry-After'] = str(SIGNUP_INTERVAL)
            return response
        self.next_attempt = self.clock() + SIGNUP_INTERVAL

        def register(store, _auth):
            # Check availability before expensive hashing; never update an account.
            if store.db.execute('SELECT 1 FROM accounts WHERE id=%s', (username,)).fetchone():
                return False
            try:
                with store.db.transaction():
                    store.register_local(username, password)
            except psycopg.errors.UniqueViolation:
                return False
            return True

        self.pending = runtime.spawn(runtime.call(register))
        def finished(task):
            self.pending = None
            if not task.cancelled():
                task.exception()  # Retrieve failures even after a client disconnect.
        self.pending.add_done_callback(finished)
        created = await asyncio.shield(self.pending)
        return json_response({'status': 'created'}, 201) if created else json_response(
            {'error': 'account_not_created'}, 409)


async def signup(request):
    gate = request.app.state.signup
    if request.query_params:
        raise ValueError('Signup does not accept URL parameters')
    if request.method == 'GET':
        return json_response({'available': gate.allowed(request)})
    # Recheck every submission before reading credentials, queuing or hashing.
    if not gate.allowed(request):
        raise Forbidden()
    values = await json_body(request, max_bytes=8192)
    if set(values) != {'username', 'password', 'confirm_password'}:
        raise ValueError('Invalid signup fields')
    Store.registration_credentials(values['username'], values['password'])
    if values['password'] != values['confirm_password']:
        raise ValueError('Passwords must match')
    return await gate.create(request.app.state.runtime, values['username'], values['password'])
