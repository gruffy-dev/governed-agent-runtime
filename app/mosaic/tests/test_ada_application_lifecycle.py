import asyncio
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_application_lifecycle import AdaApplicationLifecycle
from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration


class TestAdaApplicationLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_startup_shutdown_state_and_reentry(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, str]]:
            events.append('startup')
            yield {'resource': 'synthetic'}
            events.append('shutdown')

        lifecycle = AdaApplicationLifecycle(
            FastAPI(lifespan=lifespan), AdaApplicationAdapterConfiguration()
        )
        for _ in range(2):
            async with lifecycle.running():
                self.assertEqual(lifecycle.state, {'resource': 'synthetic'})
                with self.assertRaises(AdaApplicationError):
                    async with lifecycle.running():
                        self.fail('Concurrent startup should be rejected')
            self.assertEqual(lifecycle.state, {})
        self.assertEqual(events, ['startup', 'shutdown', 'startup', 'shutdown'])

    async def test_shutdown_still_runs_when_owner_fails(self) -> None:
        stopped = asyncio.Event()

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            try:
                yield
            finally:
                stopped.set()

        lifecycle = AdaApplicationLifecycle(
            FastAPI(lifespan=lifespan), AdaApplicationAdapterConfiguration()
        )
        with self.assertRaisesRegex(ValueError, 'owner failure'):
            async with lifecycle.running():
                raise ValueError('owner failure')
        self.assertTrue(stopped.is_set())

    async def test_lifecycle_failures_do_not_expose_private_diagnostics(self) -> None:
        for stage in ('startup', 'shutdown', 'after_shutdown'):
            with self.subTest(stage=stage):

                async def app(
                    scope: Scope, receive: Receive, send: Send, stage: str = stage
                ) -> None:
                    await receive()
                    if stage == 'startup':
                        await send(
                            {
                                'type': 'lifespan.startup.failed',
                                'message': 'synthetic-private-diagnostic',
                            }
                        )
                        return
                    await send({'type': 'lifespan.startup.complete'})
                    await receive()
                    if stage == 'shutdown':
                        await send(
                            {
                                'type': 'lifespan.shutdown.failed',
                                'message': 'synthetic-private-diagnostic',
                            }
                        )
                    else:
                        await send({'type': 'lifespan.shutdown.complete'})
                        raise RuntimeError('synthetic-private-diagnostic')

                lifecycle = AdaApplicationLifecycle(
                    app, AdaApplicationAdapterConfiguration()
                )
                with self.assertRaises(AdaApplicationError) as caught:
                    async with lifecycle.running():
                        pass
                self.assertNotIn('synthetic-private-diagnostic', str(caught.exception))

    async def test_timeout_cancels_private_task(self) -> None:
        stopped = asyncio.Event()

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        lifecycle = AdaApplicationLifecycle(
            app, AdaApplicationAdapterConfiguration(lifespan_timeout_seconds=1)
        )
        with self.assertRaises(AdaApplicationError):
            async with lifecycle.running():
                self.fail('Startup should time out')
        self.assertTrue(stopped.is_set())
