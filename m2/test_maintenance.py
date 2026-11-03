"""Synthetic admission, native Unix control and cancellation ownership checks."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import IsolatedAsyncioTestCase

from m2.release_drain import Admission, MaintenanceUnavailable, control, serve_control


class MaintenanceTests(IsolatedAsyncioTestCase):
    async def test_detached_tail_and_cancelled_worker_remain_admitted_until_finished(self):
        gate = Admission()
        token = gate.enter()
        entered, release = Event(), Event()
        tail_done = asyncio.Event()

        def blocking():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Synthetic watchdog')

        async def tail():
            await asyncio.sleep(0)
            await gate.worker(None, blocking)
            tail_done.set()

        task = gate.spawn(tail())
        gate.leave(token)
        await asyncio.to_thread(entered.wait, 2)
        draining = asyncio.create_task(gate.drain('a' * 32, timeout=2))
        await asyncio.sleep(0)
        with self.assertRaises(MaintenanceUnavailable):
            gate.enter()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(draining.done(), 'Cancelling the waiter must not drain its running worker')
        release.set()
        self.assertEqual((await draining)['phase'], 'drained')
        self.assertFalse(tail_done.is_set())
        self.assertFalse(gate.pending)

    async def test_timeout_restart_and_exact_owner_resume_never_cancel_existing_work(self):
        with TemporaryDirectory() as directory:
            fence = Path(directory) / 'fence.json'
            gate = Admission(fence)
            token = gate.enter()
            result = await gate.drain('a' * 32, timeout=0.01)
            self.assertEqual(result['phase'], 'fenced')
            gate.leave(token)
            replacement = Admission(fence)
            self.assertNotEqual(replacement.boot, gate.boot)
            with self.assertRaises(MaintenanceUnavailable):
                replacement.enter()
            with self.assertRaises(ValueError):
                replacement.resume('b' * 32)
            with self.assertRaises(ValueError):
                await replacement.drain('a' * 32)
            self.assertTrue(fence.exists())
            self.assertEqual(replacement.resume('a' * 32)['phase'], 'open')
            self.assertFalse(fence.exists())

    async def test_native_socket_has_fixed_commands_and_private_permissions(self):
        with TemporaryDirectory(prefix='kat-control-') as directory:
            path = str(Path(directory) / 'control.sock')
            gate = Admission(Path(directory) / 'fence.json')
            server = await serve_control(gate, path)
            try:
                self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
                result = await asyncio.to_thread(control, 'drain', 'c' * 32, path)
                self.assertEqual(result['phase'], 'drained')
                with self.assertRaises(ValueError):
                    await asyncio.to_thread(control, 'exec', 'c' * 32, path)
                self.assertEqual((await asyncio.to_thread(control, 'status', 'c' * 32, path))['phase'], 'drained')
                self.assertEqual((await asyncio.to_thread(control, 'resume', 'c' * 32, path))['phase'], 'open')
            finally:
                server.close()
                await server.wait_closed()
