import re
from typing import Any
from uuid import UUID, uuid4

from .ada_application_error import AdaApplicationError
from .ada_asgi_transport import AdaAsgiTransport
from ...models.identity.trusted_request_context import TrustedRequestContext


class AdaSessionApi:
    def __init__(self, transport: AdaAsgiTransport) -> None:
        """
        Bind owned session operations to the private ADA HTTP transport.

        Returned dictionaries remain internal SDK data. Public handlers must
        project them into MOSAIC response models rather than expose them.

        :param transport: Server-owned transport to the unmounted ADA app.
        """
        self._transport = transport

    async def create(self, context: TrustedRequestContext) -> dict[str, Any]:
        """
        Create an empty owned session using a server-generated UUID.

        No caller-provided identity, state, history or session ID is accepted.

        :param context: Identity produced by the trusted request dependency.

        :return: Validated internal ADA session data.

        :raises AdaApplicationError: If ADA fails or returns inconsistent ownership.
        """
        path = self._path(context)
        session_id = uuid4()
        response = await self._transport.request_json(
            'POST', path, {'session_id': str(session_id)},
        )
        return self._validate_session(response, context, session_id)

    async def list(self, context: TrustedRequestContext) -> list[dict[str, Any]]:
        """
        Fetch only sessions in the trusted application and user scope.

        :param context: Identity produced by the trusted request dependency.

        :return: Internal ADA records after validating every record's ownership.

        :raises AdaApplicationError: If ADA fails or any returned record is invalid.
        """
        response = await self._transport.request_json('GET', self._path(context))
        if not isinstance(response, list):
            raise AdaApplicationError('Private session listing returned an invalid shape.')
        return [self._validate_session(record, context) for record in response]

    async def get(
        self, context: TrustedRequestContext, conversation_id: UUID,
    ) -> dict[str, Any]:
        """
        Resolve an opaque conversation ID within the trusted ownership scope.

        :param context: Identity produced by the trusted request dependency.
        :param conversation_id: Validated UUID routing reference, not proof of ownership.

        :return: Validated internal ADA session and event data.

        :raises AdaApplicationError: If the ID is invalid, ADA rejects the lookup,
            or the returned record disagrees with the trusted scope.
        """
        if not isinstance(conversation_id, UUID):
            raise AdaApplicationError('Conversation routing requires a validated UUID.')
        response = await self._transport.request_json(
            'GET', f'{self._path(context)}/{conversation_id}',
        )
        return self._validate_session(response, context, conversation_id)

    @staticmethod
    def _path(context: TrustedRequestContext) -> str:
        """
        Build a private route using trusted, unambiguous path segments only.

        :param context: Server-derived application and user identifiers.

        :return: Private session collection path.

        :raises AdaApplicationError: If an identity cannot be represented safely.
        """
        if any(
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', identifier) is None
            for identifier in (context.app_name, context.user_id)
        ):
            raise AdaApplicationError('Trusted identity is not a safe session routing identifier.')
        return f'/apps/{context.app_name}/users/{context.user_id}/sessions'

    @staticmethod
    def _validate_session(
        response: object,
        context: TrustedRequestContext,
        conversation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """
        Reject malformed or foreign records without exposing upstream data.

        Both documented JSON aliases and Python field names are checked if
        present, so conflicting identity aliases cannot bypass validation.

        :param response: Untrusted private HTTP response data.
        :param context: Expected server-derived ownership scope.
        :param conversation_id: Expected ID for a single-session operation.

        :return: Internal session dictionary with verified identity and ID.

        :raises AdaApplicationError: If shape, identity or session ID is inconsistent.
        """
        if not isinstance(response, dict):
            raise AdaApplicationError('Private session returned an invalid shape.')
        for keys, expected in (
            (('app_name', 'appName'), context.app_name),
            (('user_id', 'userId'), context.user_id),
        ):
            values = [response[key] for key in keys if key in response]
            if not values or any(value != expected for value in values):
                raise AdaApplicationError('Private session ownership did not match trusted identity.')
        session_id = response.get('id')
        if not isinstance(session_id, str) or not session_id.strip():
            raise AdaApplicationError('Private session returned an invalid identifier.')
        if conversation_id is not None and session_id != str(conversation_id):
            raise AdaApplicationError('Private session identifier did not match the requested conversation.')
        return response
