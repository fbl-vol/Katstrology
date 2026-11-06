"""One browser Store and its worker/admission lifecycle."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from time import time

from m2.archive.deletion import Tombstones
from m2.release_drain import Admission, serve_control, SOCKET
from m2.archive.store import Store
from m2.http_boundary.web_auth import WebAuth


class BrowserRuntime:
    """One Store, on one worker thread; requests never share its transaction."""

    def __init__(self, dsn, files, ledger, siwc_factory=None, siwc_root=None, clock=None,
                 maintenance=False):
        from m2.operations.app_clock import utc_now
        self.dsn, self.files, self.ledger = dsn, files, ledger
        self.clock = clock or utc_now
        self.siwc_factory, self.siwc_root = siwc_factory, siwc_root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kat-store')
        self.store = None
        self.auth = None
        self.active_tokens = {}
        self.chat = None
        self.siwc = None
        self.admission = Admission(Path(files).parent / 'release-fence.json' if maintenance else None)
        self.maintenance = maintenance
        self.control_server = None

    async def start(self):
        def connect():
            store = Store(self.dsn, self.files, Tombstones(self.ledger))
            try:
                store.recover_open()
                self.store, self.auth = store, WebAuth(store)
            except BaseException:
                store.close()
                raise
        try:
            await self.execute(connect)
            from m2.chat.chat_jobs import ChatJobs
            self.chat = ChatJobs(self)
            if self.siwc_factory:
                self.siwc = await self.execute(lambda: self.siwc_factory(self.siwc_root))
            if self.maintenance:
                self.control_server = await serve_control(self.admission)
        except BaseException:
            if self.store:
                await self.execute(self.store.close)
            await asyncio.to_thread(self.executor.shutdown, True)
            raise

    async def execute(self, operation):
        return await self.admission.worker(self.executor, operation)

    async def offload(self, operation, *args):
        return await self.admission.worker(None, lambda: operation(*args))

    def spawn(self, coroutine):
        return self.admission.spawn(coroutine)

    async def call(self, operation):
        return await self.execute(lambda: operation(self.store, self.auth))

    def remember(self, token, session, csrf, expires):
        self.active_tokens[sha256(token.encode()).hexdigest()] = (session, csrf, expires.timestamp())

    def cached(self, token):
        if token and self.store and not self.store._blocked:
            row = self.active_tokens.get(sha256(token.encode()).hexdigest())
            if row and row[2] > time():
                return row[:2]
        return None

    async def stop(self):
        if self.control_server:
            self.control_server.close()
            await self.control_server.wait_closed()
            Path(SOCKET).unlink(missing_ok=True)
        if self.chat:
            self.chat.cancel_all()
        try:
            # A cancelled coroutine can still have an executor/provider call running.
            while self.admission.pending:
                await asyncio.gather(*tuple(self.admission.pending), return_exceptions=True)
            if self.store:
                await self.execute(lambda: (self.siwc.close() if self.siwc else None,
                                            self.store.close()))
        finally:
            self.active_tokens.clear()
            await asyncio.to_thread(self.executor.shutdown, True)
