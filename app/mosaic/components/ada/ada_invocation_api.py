from collections.abc import AsyncIterator
from contextlib import aclosing
from uuid import UUID

from starlette.types import Message

from .ada_application_error import AdaApplicationError
from .ada_asgi_transport import AdaAsgiTransport
from .ada_session_api import AdaSessionApi
from ...models.api.submit_message_request import SubmitMessageRequest
from ...models.identity.trusted_request_context import TrustedRequestContext


class AdaInvocationApi:
    def __init__(self, transport: AdaAsgiTransport) -> None:
        """
        Bind private execution to the same transport as owned session lookups.

        :param transport: Server-owned transport to the unmounted ADA application.
        """
        self._transport = transport
        self._sessions = AdaSessionApi(transport)

    async def stream(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
        message: SubmitMessageRequest,
    ) -> AsyncIterator[Message]:
        """
        Execute text only after verifying the conversation in the trusted scope.

        Construct the complete ADA body server-side. No caller identity, state,
        headers or arbitrary ADA options are forwarded. This private stream must
        be consumed by backend-owned orchestration, not a browser subscriber;
        its raw events must be projected before crossing the public boundary.

        :param context: Identity resolved by the trusted request dependency.
        :param conversation_id: UUID routing reference whose ownership is verified.
        :param message: Strict public text-only message model.

        :return: Internal ASGI messages for application-owned stream processing.

        :raises AdaApplicationError: If ownership, input or private execution fails.
        """
        if not isinstance(message, SubmitMessageRequest):
            raise AdaApplicationError(
                'Private execution requires a validated text message.'
            )
        await self._sessions.get(context, conversation_id)
        payload = {
            'app_name': context.app_name,
            'user_id': context.user_id,
            'session_id': str(conversation_id),
            'new_message': {'role': 'user', 'parts': [{'text': message.text}]},
            'streaming': True,
        }
        async with aclosing(
            self._transport.stream_response('POST', '/run_sse', payload)
        ) as stream:
            async for response in stream:
                if response['type'] == 'http.response.start' and not (
                    200 <= response['status'] < 300
                ):
                    raise AdaApplicationError(
                        'Private application rejected execution.',
                        status_code=response['status'],
                    )
                yield response
