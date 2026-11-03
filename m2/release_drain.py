"""Attempt-owned admission fence; only the local Unix socket controls maintenance.

The event loop owns admission and completion accounting. Cancelling a waiter does
not cancel a worker future or release its work count. A persisted fence survives
an interrupted controller/container; only its exact attempt can reopen admission.
"""

import asyncio
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import socket
import struct
from uuid import uuid4

from starlette.responses import JSONResponse

ATTEMPT = re.compile(r'[a-f0-9]{32}\Z')
SOCKET = '/tmp/kat-release-control.sock'
DRAIN_SECONDS = 300  # Release-abort bound, not a maximum legitimate turn duration.
_admitted = ContextVar('kat_admitted_work', default=False)


class MaintenanceUnavailable(RuntimeError):
    pass


class Admission:
    def __init__(self, fence=None):
        self.fence = Path(fence) if fence else None
        self.attempt = None
        self.phase = 'open'
        self.boot = uuid4().hex
        self.pending = set()
        self.requests = 0
        self.changed = asyncio.Event()
        if self.fence and self.fence.exists():
            value = json.loads(self.fence.read_text())
            if set(value) != {'attempt'} or not ATTEMPT.fullmatch(value['attempt']):
                raise ValueError('Invalid persisted maintenance fence')
            self.attempt, self.phase = value['attempt'], 'fenced'

    def enter(self, *, cancellation=False):
        if self.phase != 'open' and not (cancellation and self.phase == 'draining'):
            raise MaintenanceUnavailable('Release maintenance')
        self.requests += 1
        return _admitted.set(True)

    def leave(self, token):
        _admitted.reset(token)
        self.requests -= 1
        self.changed.set()

    def track(self, future):
        self.pending.add(future)
        def finished(done):
            self.pending.discard(done)
            self.changed.set()
        future.add_done_callback(finished)
        return future

    def spawn(self, coroutine):
        if self.phase != 'open' and not _admitted.get():
            coroutine.close()
            raise MaintenanceUnavailable('Release maintenance')
        return self.track(asyncio.create_task(coroutine))

    async def worker(self, executor, operation):
        future = self.track(asyncio.get_running_loop().run_in_executor(executor, operation))
        return await asyncio.shield(future)

    def persist(self):
        if self.fence:
            self.fence.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with open(self.fence, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as output:
                output.write(json.dumps({'attempt': self.attempt}) + '\n')
                output.flush()
                os.fsync(output.fileno())
            self.sync()

    def sync(self):
        if self.fence:
            fd = os.open(self.fence.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    async def drain(self, attempt, timeout=DRAIN_SECONDS):
        if not ATTEMPT.fullmatch(attempt) or self.attempt is not None:
            raise ValueError('Maintenance already owned; no drain replay')
        # No await between fence and persistence: new requests cannot slip in.
        self.attempt, self.phase = attempt, 'draining'
        self.persist()
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while self.requests or self.pending:
                self.changed.clear()
                async with asyncio.timeout_at(deadline):
                    await self.changed.wait()
            self.phase = 'drained'
        except TimeoutError:
            self.phase = 'fenced'  # Do not cancel paid work or reopen on timeout.
        return self.status()

    def resume(self, attempt):
        if attempt != self.attempt or self.phase == 'open':
            raise ValueError('Maintenance owner differs')
        if self.fence:
            if json.loads(self.fence.read_text()) != {'attempt': attempt}:
                raise ValueError('Persisted maintenance owner differs')
            self.fence.unlink()
            self.sync()
        self.attempt, self.phase = None, 'open'
        return self.status()

    def status(self):
        return {'phase': self.phase, 'attempt': self.attempt, 'boot': self.boot}


class AdmissionBoundary:
    """Count complete HTTP lifetimes, including streamed response cleanup.

    Effectful GETs (catalog refresh/OAuth) are fenced too. Anonymous session
    readiness is read-only and stays reachable; no public maintenance route exists.
    """
    def __init__(self, app, admission):
        self.app, self.admission = app, admission

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        controlled = scope['type'] == 'http' and path.startswith(('/api/', '/auth/'))
        anonymous_probe = (path == '/api/session' and scope.get('method') == 'GET'
                           and not any(key == b'cookie' for key, _ in scope.get('headers', [])))
        if not controlled or anonymous_probe:
            return await self.app(scope, receive, send)
        try:
            token = self.admission.enter(cancellation=path.endswith('/cancel'))
        except MaintenanceUnavailable:
            response = JSONResponse({'error': 'release_maintenance'}, status_code=503,
                                    headers={'Cache-Control': 'no-store', 'Retry-After': '30'})
            return await response(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            self.admission.leave(token)


async def serve_control(admission, path=SOCKET):
    async def handle(reader, writer):
        try:
            peer = writer.get_extra_info('socket')
            _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid not in (0, os.getuid()):
                raise PermissionError('Local maintenance peer denied')
            line = await asyncio.wait_for(reader.readline(), 3)
            request = json.loads(line)
            if (len(line) > 256 or set(request) != {'action', 'attempt'}
                    or not isinstance(request['attempt'], str) or not ATTEMPT.fullmatch(request['attempt'])):
                raise ValueError('Invalid maintenance request')
            action, attempt = request['action'], request['attempt']
            if action == 'drain':
                result = await admission.drain(attempt)
            elif action == 'resume':
                result = admission.resume(attempt)
            elif action == 'status':
                result = admission.status()
            else:
                raise ValueError('Unsupported maintenance action')
            writer.write(json.dumps(result).encode() + b'\n')
            await writer.drain()
        except (Exception, asyncio.CancelledError):
            # No error details or activity counts cross this control boundary.
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    # /tmp is container-private tmpfs. A stale socket is never an ownership signal.
    if Path(path).exists():
        raise ValueError('Maintenance socket already exists')
    server = await asyncio.start_unix_server(handle, path=path, limit=256)
    os.chmod(path, 0o600)
    return server


def control(action, attempt, path=SOCKET):
    """Fixed gateway client, executed inside the exact owned app container."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(DRAIN_SECONDS + 5)
        connection.connect(path)
        connection.sendall(json.dumps({'action': action, 'attempt': attempt}).encode() + b'\n')
        with connection.makefile('rb') as stream:
            line = stream.readline(1025)
        if len(line) > 1024 or not line.endswith(b'\n'):
            raise ValueError('Unconfirmed maintenance outcome')
        return json.loads(line)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('drain', 'resume', 'status'))
    parser.add_argument('attempt')
    args = parser.parse_args()
    if not ATTEMPT.fullmatch(args.attempt):
        parser.error('Invalid attempt')
    print(json.dumps(control(args.action, args.attempt)))
