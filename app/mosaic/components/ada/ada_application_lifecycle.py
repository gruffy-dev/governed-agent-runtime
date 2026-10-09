import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from starlette.types import ASGIApp, Message

from .ada_application_error import AdaApplicationError
from ...models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration


class AdaApplicationLifecycle:
    def __init__(
        self,
        application: ASGIApp,
        configuration: AdaApplicationAdapterConfiguration,
    ) -> None:
        """
        Own private application startup and shutdown through ASGI messages.

        :param application: Private application produced by the ADA factory.
        :param configuration: Validated startup and shutdown timeouts.
        """
        self._application = application
        self._configuration = configuration
        self._active = False
        self._state: dict[str, Any] = {}

    @property
    def state(self) -> dict[str, Any]:
        """
        Expose lifespan state for shallow copying into private request scopes.

        :return: Application infrastructure state, never caller-owned identity.
        """
        return self._state

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """
        Start the private application once and shut it down on context exit.

        :return: Async context keeping the private application running.

        :raises AdaApplicationError: If lifecycle acknowledgement fails or times out.
        """
        if self._active:
            raise AdaApplicationError(
                'Private application lifecycle is already active.'
            )
        self._active = True
        self._state.clear()
        commands: asyncio.Queue[Message] = asyncio.Queue(maxsize=1)
        replies: asyncio.Queue[Message] = asyncio.Queue(maxsize=1)
        task = asyncio.create_task(
            self._application(
                {
                    'type': 'lifespan',
                    'asgi': {'version': '3.0', 'spec_version': '2.0'},
                    'state': self._state,
                },
                commands.get,
                replies.put,
            )
        )
        try:
            await self._exchange(commands, replies, task, 'startup')
            try:
                yield
            finally:
                await self._exchange(commands, replies, task, 'shutdown')
                try:
                    await asyncio.wait_for(
                        task, self._configuration.lifespan_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    raise
                except Exception:  # noqa: BLE001 - SDK diagnostics must not cross the public boundary.
                    raise AdaApplicationError(
                        'Private application shutdown failed.'
                    ) from None
        except asyncio.TimeoutError:
            raise AdaApplicationError(
                'Private application lifecycle timed out.'
            ) from None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._active = False
            self._state.clear()

    async def _exchange(
        self,
        commands: asyncio.Queue[Message],
        replies: asyncio.Queue[Message],
        application_task: asyncio.Task[None],
        stage: str,
    ) -> None:
        """
        Require a complete acknowledgement for one lifecycle transition.

        :param commands: Queue carrying lifecycle commands to the application.
        :param replies: Queue carrying application acknowledgements.
        :param application_task: Running ASGI lifespan task.
        :param stage: Startup or shutdown transition name.

        :raises AdaApplicationError: If the app exits, rejects or omits acknowledgement.
        """
        await commands.put({'type': f'lifespan.{stage}'})
        reply_task = asyncio.create_task(replies.get())
        try:
            completed, _ = await asyncio.wait(
                (reply_task, application_task),
                timeout=self._configuration.lifespan_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reply_task in completed:
                reply = reply_task.result()
            elif not replies.empty():
                reply = replies.get_nowait()
            else:
                raise AdaApplicationError(
                    f'Private application {stage} was not acknowledged.'
                )
            if reply.get('type') != f'lifespan.{stage}.complete':
                raise AdaApplicationError(f'Private application {stage} failed.')
        finally:
            reply_task.cancel()
            await asyncio.gather(reply_task, return_exceptions=True)
