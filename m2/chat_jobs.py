"""One Store worker archives each turn before publishing stable browser events."""

import asyncio
from collections import deque
import json
from threading import Event

from m2.local_model import DEFAULT_MODEL, model_at
from m2.gateway import CHART_PREFIX, EVENT_PREFIX, REFERENCE_PREFIX, turn_steps
from m2.recall import PromptBudgetError, rebuild_one
from m2.provider.responses import ResponsesModel
from m2.provider.steps import ProviderFlush, ProviderStep, next_provider
from m2.siwc import ProviderFailure
from m2.title_work import TitleWork, generate_title


class LocalModel:
    """Load the small synthetic Qwen fixture only after the user-input ACK."""

    def __init__(self):
        self.model = None

    def _load(self):
        if self.model is None:
            self.model = model_at(DEFAULT_MODEL)
        return self.model

    def tokenize(self, *args, **kwargs):
        return self._load().tokenize(*args, **kwargs)

    def create_completion(self, *args, **kwargs):
        return self._load().create_completion(*args, **kwargs)

    def close(self):
        if self.model:
            self.model.close()


class TurnJob:
    def __init__(self, owner, conversation_id, turn_id, fingerprint):
        self.owner, self.conversation_id, self.turn_id = owner, conversation_id, turn_id
        self.fingerprint = fingerprint
        self.ack = asyncio.get_running_loop().create_future()
        self.cancel = Event()
        self.changed = asyncio.Event()
        self.events = deque(maxlen=512)
        self.finished = False
        self.status = 'open'

    def publish(self, event):
        self.events.append(event)
        self.changed.set()

    def finish(self, status):
        self.status = status
        self.finished = True
        self.changed.set()


class ChatJobs:
    def __init__(self, runtime, model_factory=LocalModel):
        self.runtime = runtime
        self.model_factory = model_factory
        self.jobs = {}
        self.rebuilds = {}

    async def submit(self, session, conv_id, turn_id, request, selected_people,
                     parent_id='@active', revision_kind='normal', replaces_turn_id=None,
                     mode='local', model_slug=None, chart_file=None,
                     reporting_zone=None, resolve_active=False, archived_selection=None,
                     admission=None, selected_result=None):
        owner = session.owner_id
        key = owner, conv_id, turn_id
        fingerprint = json.dumps([request, selected_people, parent_id, revision_kind,
                                  replaces_turn_id, mode, model_slug, chart_file,
                                  reporting_zone, selected_result], sort_keys=True)
        job = self.jobs.get(key)
        if job:
            if job.fingerprint != fingerprint:
                raise ValueError('Turn ID reused with changed input or selection')
            return await asyncio.shield(job.ack)
        job = TurnJob(owner, conv_id, turn_id, fingerprint)
        self.jobs[key] = job
        self.runtime.spawn(self._run(job, session, request, selected_people, parent_id,
                                      revision_kind, replaces_turn_id, mode, model_slug,
                                      chart_file, reporting_zone, resolve_active, archived_selection,
                                      admission, selected_result))
        return await asyncio.shield(job.ack)

    async def _run(self, job, session, request, selected_people, parent_id,
                   revision_kind, replaces_turn_id, mode, model_slug, chart_file,
                   reporting_zone, resolve_active, archived_selection, admission, selected_result):
        loop = asyncio.get_running_loop()
        store = self.runtime.store
        acknowledged = False
        model = None

        def deliver(event):
            loop.call_soon_threadsafe(job.publish, event)

        def acknowledge(value):
            nonlocal acknowledged
            # Event zero and its selected-version rows have already committed.
            snapshot = store.read_turn(session, job.conversation_id, job.turn_id, event_limit=1)
            deliver(snapshot['events'][0])
            acknowledged = True
            loop.call_soon_threadsafe(job.ack.set_result, {**value, 'turn': snapshot})

        def prepare():
            nonlocal model
            if admission and self.runtime.siwc.binding(job.owner) != admission.binding:
                raise ProviderFailure('selected_account_changed')  # Before any archive write.
            if archived_selection is not None:
                selected_versions = archived_selection
            elif resolve_active:
                from m2.people import People
                selected_versions = People(store).resolve_active(session, selected_people)
            else:
                selected_versions = selected_people
            model = (ResponsesModel(self.runtime.siwc, job.owner, model_slug, admission) if mode == 'chatgpt'
                     else None if request.startswith((CHART_PREFIX, EVENT_PREFIX, REFERENCE_PREFIX))
                     else self.model_factory())
            return turn_steps(store, session, job.conversation_id, job.turn_id, request,
                              model, deliver, parent_id=parent_id,
                              revision_kind=revision_kind, replaces_turn_id=replaces_turn_id,
                              selected_people=selected_versions, cancelled=job.cancel.is_set,
                              acknowledge=acknowledge,
                              model_provider='chatgpt_plan' if mode == 'chatgpt' else 'local',
                              model_slug=model_slug, chart_file=chart_file, clock=self.runtime.clock,
                              reporting_zone=reporting_zone,
                              interpret_commands=not (resolve_active or archived_selection is not None),
                              defer_provider=True, selected_result=selected_result)

        def archive_failure(failure):
            if acknowledged:
                try:
                    details = (failure.public() if isinstance(failure, ProviderFailure)
                               else {'reason': 'selected_context_exceeds_model_budget'}
                               if isinstance(failure, PromptBudgetError) else
                               {'reason': 'provider_transport_or_storage_failed'
                                if mode == 'chatgpt' else 'local_inference_or_storage_failed'})
                    sequence = store.append(session, job.conversation_id, job.turn_id,
                                            'error', details)
                    deliver(store.read_event(session, job.conversation_id, job.turn_id, sequence))
                    return 'error'
                except Exception:
                    # Storage failure leaves an open original for startup recovery.
                    return 'open'
            loop.call_soon_threadsafe(job.ack.set_exception,
                                      failure if isinstance(failure, ProviderFailure) else
                                      ValueError('Turn could not be archived'))
            return 'error'

        try:
            steps = await self.runtime.execute(prepare)
            status = await self._drive(steps)
        except Exception as failure:
            try:
                status = await self.runtime.execute(lambda: archive_failure(failure))
            except Exception:
                status = 'open'
                if not job.ack.done():
                    job.ack.set_exception(RuntimeError('Turn storage unavailable'))
        finally:
            close = getattr(model, 'close', None)
            if close:
                try:
                    await self.runtime.offload(close)
                except Exception:
                    pass

        job.finish(status)
        if (status == 'complete' and mode == 'chatgpt' and archived_selection is None
                and not request.startswith((CHART_PREFIX, EVENT_PREFIX, REFERENCE_PREFIX))):
            self.runtime.spawn(self._title(session, job.conversation_id, job.turn_id))
        if status == 'complete':
            self._schedule_rebuild(session, job.conversation_id)
        if len(self.jobs) > 64:
            for key, item in list(self.jobs.items()):
                if len(self.jobs) <= 64:
                    break
                if item.finished:
                    del self.jobs[key]

    async def _drive(self, steps):
        """Advance Store effects on its worker and provider iterators off that worker."""
        active_stream = response = provider_error = next_task = None

        def advance():
            nonlocal response, provider_error
            try:
                if provider_error is not None:
                    failure, provider_error = provider_error, None
                    step = steps.throw(failure)
                elif response is not None:
                    step, response = steps.send(response), None
                else:
                    step = next(steps)
                return True, step
            except StopIteration as done:
                return False, done.value

        try:
            while True:
                ready, step = await self.runtime.execute(advance)
                if not ready:
                    return step
                if not isinstance(step, ProviderStep):
                    raise RuntimeError('Unexpected gateway step')
                if active_stream is not step.stream:
                    if next_task is not None:
                        raise RuntimeError('Provider stream switched before its read completed')
                    if active_stream is not None:
                        await self.runtime.offload(active_stream.close)
                    active_stream = step.stream
                # A shielded read may remain in flight while the Store worker
                # commits a timer-flushed suffix. Never read a stream twice at once.
                if next_task is None:
                    next_task = self.runtime.spawn(self.runtime.offload(next_provider, active_stream))
                try:
                    if step.flush_pending:
                        response = await asyncio.wait_for(asyncio.shield(next_task), timeout=0.15)
                    else:
                        response = await next_task
                    next_task = None
                except TimeoutError:
                    response = (True, ProviderFlush())
                except Exception as failure:
                    next_task = None
                    provider_error = failure
        finally:
            if next_task is not None:
                try:
                    await next_task
                except Exception:
                    pass
            try:
                await self.runtime.execute(steps.close)
            except Exception:
                pass
            if active_stream is not None:
                try:
                    await self.runtime.offload(active_stream.close)
                except Exception:
                    pass

    def _schedule_rebuild(self, session, conversation_id):
        key = session.owner_id, conversation_id
        previous = self.rebuilds.get(key)
        if previous and not previous.done():
            return
        task = self.runtime.spawn(self._rebuild(session, conversation_id))
        self.rebuilds[key] = task
        task.add_done_callback(lambda finished: self.rebuilds.pop(key, None)
                               if self.rebuilds.get(key) is finished else None)

    async def _rebuild(self, session, conversation_id):
        # The queue is durable. Coalesce successive completed turns, but leave
        # a failed or changing epoch pending for an explicit recovery rebuild.
        await asyncio.sleep(0)
        for _ in range(3):
            try:
                row = await self.runtime.execute(lambda: self.runtime.store.db.execute('''
                    SELECT epoch FROM rebuild_queue WHERE owner_id=%s AND conversation_id=%s
                ''', (session.owner_id, conversation_id)).fetchone())
                if not row:
                    return
                if await self.runtime.execute(lambda: rebuild_one(
                        self.runtime.store, session, conversation_id, row['epoch'])):
                    return
            except Exception:
                return

    async def _title(self, session, conversation_id, turn_id):
        try:
            source = await self.runtime.call(lambda store, _: TitleWork(store).prepare(
                session, conversation_id, turn_id))
            if not source:
                return
            try:
                title = await self.runtime.offload(generate_title, self.runtime.siwc,
                                                session.owner_id, source)
            except Exception:
                # An optional title request cannot change a completed chat or replay it.
                title = None
            await self.runtime.call(lambda store, _: TitleWork(store).finish(
                session, conversation_id, source, title))
        except Exception:
            # The committed turn remains authoritative; no automatic retry.
            pass

    def cancel(self, owner, conv_id, turn_id):
        job = self.jobs.get((owner, conv_id, turn_id))
        if job and not job.finished:
            job.cancel.set()
            return True
        return False

    def cancel_all(self):
        for job in self.jobs.values():
            if not job.finished:
                job.cancel.set()
        for rebuild in self.rebuilds.values():
            rebuild.cancel()

    async def events(self, session, conv_id, turn_id, after=-1):
        """Replay durable DB pages; live events are committed before publication."""
        cursor = after
        job = self.jobs.get((session.owner_id, conv_id, turn_id))
        if job:
            while not job.finished:
                if job.events and job.events[0]['sequence'] > cursor + 1:
                    # The bounded live ring was overrun. Wait until finished,
                    # then replay the missing prefix from the committed DB.
                    await asyncio.sleep(0.1)
                    continue
                for event in list(job.events):
                    if event['sequence'] > cursor:
                        yield event
                        cursor = event['sequence']
                if job.finished:
                    break
                job.changed.clear()
                if job.finished or any(event['sequence'] > cursor for event in job.events):
                    continue
                try:
                    await asyncio.wait_for(job.changed.wait(), timeout=15)
                except TimeoutError:
                    yield None  # SSE keepalive; no invented archive event.
        while True:
            page = await self.runtime.call(lambda store, _: store.read_turn(
                session, conv_id, turn_id, event_offset=cursor + 1, event_limit=64))
            for event in page['events']:
                yield event
                cursor = event['sequence']
            if page['next_event_offset'] is None:
                return
