from typing import Any

from pydantic import BaseModel

from ...models.api.api_error_response import ApiErrorResponse
from ...models.api.conversation_conflict_response import ConversationConflictResponse
from ...models.api.conversation_detail import ConversationDetail
from ...models.api.conversation_list_response import ConversationListResponse
from ...models.api.create_conversation_request import CreateConversationRequest
from ...models.api.invocation_status import InvocationStatus
from ...models.api.invocation_stream_event import InvocationStreamEvent
from ...models.api.submit_message_request import SubmitMessageRequest
from ...models.identity.authentication_error_response import AuthenticationErrorResponse
from ...models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration


class ConversationApiContract:
    def __init__(
        self, authentication_configuration: PilotAuthenticationConfiguration
    ) -> None:
        """
        Bind the public contract to the configured browser-cookie name.

        :param authentication_configuration: Pilot cookie configuration.
        """
        self._authentication_configuration = authentication_configuration

    def build(self) -> dict[str, Any]:
        """
        Generate the versioned contract solely from MOSAIC-owned models.

        Conversation operations are planned contracts until their runtime
        handlers are implemented. This document registers no placeholder
        conversation endpoints and contains no raw ADA schemas.

        :return: OpenAPI document for the planned public conversation API.
        """
        schemas: dict[str, Any] = {}
        for model in (
            CreateConversationRequest,
            SubmitMessageRequest,
            ConversationDetail,
            ConversationListResponse,
            InvocationStatus,
            InvocationStreamEvent,
            ApiErrorResponse,
            AuthenticationErrorResponse,
            ConversationConflictResponse,
        ):
            schema = model.model_json_schema(
                ref_template='#/components/schemas/{model}'
            )
            schemas.update(schema.pop('$defs', {}))
            schemas[model.__name__] = schema

        paths = {
            '/api/v1/conversations': {
                'post': self._operation(
                    'createConversation',
                    'Create an owned conversation with a server-generated ID.',
                    ConversationDetail,
                    success_status=201,
                    request_model=CreateConversationRequest,
                ),
                'get': self._operation(
                    'listConversations',
                    'List only owned conversations in descending last-activity order.',
                    ConversationListResponse,
                ),
            },
            '/api/v1/conversations/{conversation_id}': {
                'get': self._operation(
                    'getConversation',
                    'Return complete public history. Unknown and foreign IDs both return 404.',
                    ConversationDetail,
                    owned_conversation=True,
                ),
            },
            '/api/v1/conversations/{conversation_id}/messages': {
                'post': self._operation(
                    'submitMessage',
                    'Submit text using fetch POST and consume named SSE events. '
                    'Disconnection does not cancel work. A busy conversation returns '
                    '409 immediately; the message is not queued.',
                    InvocationStreamEvent,
                    request_model=SubmitMessageRequest,
                    owned_conversation=True,
                    streaming=True,
                ),
            },
            '/api/v1/conversations/{conversation_id}/invocations/current': {
                'get': self._operation(
                    'getCurrentInvocation',
                    'Return current or most recent invocation status, or idle when none exists. '
                    'Process termination interrupts work; restart never resumes it.',
                    InvocationStatus,
                    owned_conversation=True,
                ),
            },
            '/api/v1/conversations/{conversation_id}/invocations/current/cancel': {
                'post': self._operation(
                    'cancelCurrentInvocation',
                    'Cancel owned active work and acknowledge only after terminal cancellation. '
                    'Repeated cancellation is idempotent. Idle or already terminal invocations '
                    'return their unchanged status. Unknown or foreign conversations return 404.',
                    InvocationStatus,
                    owned_conversation=True,
                ),
            },
        }
        return {
            'openapi': '3.1.0',
            'info': {
                'title': 'MOSAIC conversation API',
                'version': '1.0.0',
                'description': (
                    'Release 1 conversation contract. Operations marked planned are not yet '
                    'available. All handlers must use the trusted request-context dependency; '
                    'application, user, workspace and Skill state are server-owned. Browser '
                    'access is same-origin. Send exactly one bearer token or pilot cookie. '
                    'Sign in at POST /api/v1/auth/token with a token JSON field; sign out at '
                    'POST /api/v1/auth/logout. Tokens are never placed in URLs.'
                ),
            },
            'paths': paths,
            'x-mosaic-error-codes': {
                '400': 'invalid_request',
                '401': 'unauthorized',
                '403': 'forbidden',
                '404': 'conversation_not_found',
                '409': 'conversation_busy',
                '500': 'internal_error',
                'failed_sse_event': 'invocation_failed',
            },
            'x-mosaic-authentication-examples': [
                {
                    'label': 'Bearer authentication',
                    'command': 'curl --noproxy "*" -H "Authorization: Bearer YOUR_PILOT_TOKEN" '
                    'http://127.0.0.1:8000/api/v1/conversations',
                },
                {
                    'label': 'Cookie authentication after sign-in',
                    'command': 'curl --noproxy "*" -b pilot-cookie-file '
                    'http://127.0.0.1:8000/api/v1/conversations',
                },
            ],
            'components': {
                'schemas': schemas,
                'securitySchemes': {
                    'BearerAuth': {'type': 'http', 'scheme': 'bearer'},
                    'PilotCookie': {
                        'type': 'apiKey',
                        'in': 'cookie',
                        'name': self._authentication_configuration.cookie_name,
                    },
                },
            },
        }

    def _operation(
        self,
        operation_id: str,
        description: str,
        response_model: type[BaseModel],
        *,
        success_status: int = 200,
        request_model: type[BaseModel] | None = None,
        owned_conversation: bool = False,
        streaming: bool = False,
    ) -> dict[str, Any]:
        """
        Describe one authenticated public operation and its failure contract.

        :param operation_id: Stable operation name for API consumers.
        :param description: Behaviour and ownership requirements.
        :param response_model: Public response or individual SSE data model.
        :param success_status: Successful HTTP status.
        :param request_model: Optional strictly validated JSON request model.
        :param owned_conversation: Whether the path contains an owned UUID.
        :param streaming: Whether the successful response is an SSE stream.

        :return: OpenAPI operation with explicit authentication requirements.
        """
        responses: dict[str, Any] = {
            str(success_status): self._response(
                response_model, 'Successful response.', streaming
            ),
            '400': self._response(ApiErrorResponse, 'Malformed or invalid request.'),
            '401': self._response(
                AuthenticationErrorResponse, 'Sign-in or valid bearer token required.'
            ),
            '403': self._response(AuthenticationErrorResponse, 'Access denied.'),
            '500': self._response(
                ApiErrorResponse,
                'Safe internal failure; no provider data or stack trace.',
            ),
        }
        operation: dict[str, Any] = {
            'operationId': operation_id,
            'description': description,
            'security': [{'BearerAuth': []}, {'PilotCookie': []}],
            'x-mosaic-implementation': 'planned',
            'x-mosaic-identity-source': 'trusted_request_context',
            'responses': responses,
        }
        responses['403']['headers'].pop('WWW-Authenticate')
        if request_model is not None:
            operation['requestBody'] = {
                'required': True,
                'content': {
                    'application/json': {'schema': self._reference(request_model)}
                },
            }
        if owned_conversation:
            operation['parameters'] = [
                {
                    'name': 'conversation_id',
                    'in': 'path',
                    'required': True,
                    'description': 'Opaque routing identifier; ownership is checked against trusted identity.',
                    'schema': {'type': 'string', 'format': 'uuid'},
                }
            ]
            responses['404'] = self._response(
                ApiErrorResponse,
                'Conversation unavailable; foreign IDs are not disclosed.',
            )
        if streaming:
            responses['409'] = self._response(
                ConversationConflictResponse,
                'This conversation already has an active invocation. Wait for completion or cancel it.',
            )
            operation['x-mosaic-sse'] = {
                'events': ['started', 'text_delta', 'completed', 'failed', 'cancelled'],
                'framing': 'event: <event name>\ndata: <InvocationStreamEvent JSON>\n\n',
                'terminal_events': ['completed', 'failed', 'cancelled'],
                'sequence': 'started, zero or more text_delta events, then exactly one terminal event.',
                'errors': 'Before streaming, return the HTTP error envelope; after streaming starts, emit failed.',
                'reconnection': 'No stream replay. Reopen history and check current invocation status.',
                'privacy': 'Public assistant text and safe failures only; no tool results or internal state.',
            }
            responses[str(success_status)]['headers']['X-Accel-Buffering'] = {
                'description': 'Disable intermediary buffering.',
                'schema': {'type': 'string', 'const': 'no'},
            }
        return operation

    def _response(
        self,
        model: type[BaseModel],
        description: str,
        streaming: bool = False,
    ) -> dict[str, Any]:
        """
        Describe a correlated JSON response or a sequence of SSE frames.

        :param model: Schema for JSON or each SSE frame data payload.
        :param description: Public response meaning.
        :param streaming: Whether the body uses SSE framing rather than JSON.

        :return: OpenAPI response with no-store and correlation headers.
        """
        media_type = 'text/event-stream' if streaming else 'application/json'
        schema = {'type': 'string'} if streaming else self._reference(model)
        response: dict[str, Any] = {
            'description': description,
            'headers': {
                'X-Correlation-ID': {
                    'description': 'Server-generated correlation identifier shared with logs and SSE events.',
                    'schema': {'type': 'string', 'format': 'uuid'},
                },
                'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}},
            },
            'content': {media_type: {'schema': schema}},
        }
        if streaming:
            response['content'][media_type]['x-mosaic-event-schema'] = self._reference(
                model
            )
        if model is AuthenticationErrorResponse:
            response['headers']['WWW-Authenticate'] = {
                'description': 'Bearer challenge on 401 responses only.',
                'schema': {'type': 'string', 'const': 'Bearer'},
            }
        return response

    @staticmethod
    def _reference(model: type[BaseModel]) -> dict[str, str]:
        """
        Reference one generated public schema without embedding duplicates.

        :param model: Public response or request model.

        :return: OpenAPI component schema reference.
        """
        return {'$ref': f'#/components/schemas/{model.__name__}'}
