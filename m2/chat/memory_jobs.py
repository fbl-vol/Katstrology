"""Idle/coalesced memory with its own single network slot, never Store inference."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from m2.chat.memory_apply import apply
from m2.chat.memory_evidence import snapshot
from m2.chat.memory_provider import analyze
from m2.chat.memory_work import GLOBAL_INTERVAL_SECONDS, IDLE_SECONDS, MemoryWork
from m2.provider.siwc import ProviderFailure


class MemoryJobs:
    def __init__(self, runtime):
        self.runtime = runtime
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kat-memory')
        self.timer = None
        self.task = None
        self.foreground_requests = 0
        self.closing = False

    @property
    def busy(self):
        return self.foreground_requests or any(not job.finished for job in self.runtime.chat.jobs.values())

    def foreground_enter(self):
        self.foreground_requests += 1
        self._cancel_timer()

    def foreground_leave(self):
        self.foreground_requests -= 1
        self.notify()

    def _cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def notify(self, delay=IDLE_SECONDS):
        self._cancel_timer()
        if (self.closing or self.busy or self.runtime.admission.phase != 'open' or
                self.task is not None and not self.task.done()):
            return
        self.timer = asyncio.get_running_loop().call_later(float(delay), self._start)

    def _start(self):
        self.timer = None
        if self.closing or self.busy or self.runtime.admission.phase != 'open':
            return
        self.task = self.runtime.spawn(self._run())

    async def _run(self):
        work = None
        next_delay = None
        try:
            work = await self.runtime.execute(lambda: MemoryWork(self.runtime.store).due())
            if work is None:
                return
            if work['delay'] > 0:
                next_delay = work['delay']
                return
            if self.busy or self.closing or self.runtime.admission.phase != 'open':
                return

            def prepare():
                bridge = self.runtime.siwc
                if bridge is None:
                    return None
                bridge.background_access(work['owner_id'], work['account_binding'])
                evidence = snapshot(self.runtime.store, self.runtime.auth, work)
                if evidence is None or not MemoryWork(self.runtime.store).claim(work):
                    return None
                return evidence

            try:
                evidence = await self.runtime.execute(prepare)
            except ProviderFailure as failure:
                # This availability failure is raised before claim/network. Leave
                # the pending generation and paid-attempt budget untouched. The
                # same exception after claim remains terminal below, never retried.
                if failure.reason != 'background_capacity_unavailable':
                    raise
                # Rotate the queue position so one expired/unavailable account
                # cannot indefinitely starve other owners' ready work.
                await self.runtime.execute(lambda: MemoryWork(self.runtime.store).defer(work))
                next_delay = GLOBAL_INTERVAL_SECONDS
                return
            if evidence is None:
                await self._finish(work, 'ineligible')
                next_delay = IDLE_SECONDS
                return
            if self.busy or self.closing or self.runtime.admission.phase != 'open':
                await self._finish(work, 'superseded_before_request')
                return
            # Actual worker future is admission-tracked and shielded. Cancelling a
            # waiter cannot make shutdown/drain forget an in-flight provider read.
            actions = await self.runtime.admission.worker(self.executor,
                lambda: analyze(self.runtime.siwc, work, evidence))
            if self.busy or self.closing or self.runtime.admission.phase != 'open':
                outcome = 'superseded_after_request'
            else:
                outcome = await self.runtime.execute(lambda: apply(self.runtime.store,
                    self.runtime.auth, self.runtime.siwc, work, evidence, actions))
            await self._finish(work, outcome)
            next_delay = IDLE_SECONDS
        except Exception:
            # Optional memory cannot emit a chat error, retain raw provider output
            # or retry an ambiguous paid request. The durable attempt stays final.
            if work is not None:
                try:
                    await self._finish(work, 'failed')
                    next_delay = IDLE_SECONDS
                except Exception:
                    pass  # Startup abandons the already-marked attempt after storage failure.
        finally:
            self.task = None
            if next_delay is not None:
                self.notify(next_delay)

    async def _finish(self, work, outcome):
        await self.runtime.execute(lambda: MemoryWork(self.runtime.store).finish(work, outcome))

    def stop(self):
        self.closing = True
        self._cancel_timer()

    async def close(self):
        self.stop()
        await asyncio.to_thread(self.executor.shutdown, True)
