from typing import Any

from pydantic import BaseModel

from ...models.api.api_error_response import ApiErrorResponse
from ...models.api.conversation_detail import ConversationDetail
from ...models.api.conversation_job_detail import ConversationJobDetail
from ...models.api.conversation_list_response import ConversationListResponse
from ...models.api.create_conversation_request import CreateConversationRequest
from ...models.api.submit_message_request import SubmitMessageRequest
from ...models.identity.authentication_error_response import AuthenticationErrorResponse
from ...models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration


class ConversationApiContract:
    def __init__(
        self, authentication_configuration: PilotAuthenticationConfiguration,
        *, implemented_operations: tuple[str, ...] = (),
    ) -> None:
        """
        Bind the public contract to the configured browser-cookie name.

        :param authentication_configuration: Pilot cookie configuration.
        :param implemented_operations: Operation IDs registered by this backend.
        """
        self._authentication_configuration = authentication_configuration
        self._implemented_operations = implemented_operations

    def build(self) -> dict[str, Any]:
        """
        Generate the conversation contract with native ADK SSE framing.

        Mark operations available only when the composing backend registers
        their handlers. The stream retains ADK answer fields, not SDK schemas.

        :return: OpenAPI document for the planned public conversation API.
        """
        schemas: dict[str, Any] = {}
        for model in (
            CreateConversationRequest,
            SubmitMessageRequest,
            ConversationDetail,
            ConversationJobDetail,
            ConversationListResponse,
            ApiErrorResponse,
            AuthenticationErrorResponse,
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
                    'Return complete public history and the latest background job ID and status, if any. '
                    'Unknown and foreign IDs both return 404.',
                    ConversationDetail,
                    owned_conversation=True,
                ),
            },
            '/api/v1/conversations/{conversation_id}/messages': {
                'post': self._operation(
                    'submitMessage',
                    'Submit text using fetch POST and consume ADK data events. '
                    'Browser disconnection stops execution; saved session history remains. '
                    'No background continuation or stream replay is provided.',
                    ApiErrorResponse,
                    request_model=SubmitMessageRequest,
                    owned_conversation=True,
                    streaming=True,
                ),
            },
        }
        paths['/api/v1/conversations/{conversation_id}/jobs'] = {
            'post': self._operation(
                'submitConversationJob', 'Queue an owned goal and return a job ID.',
                ConversationJobDetail, success_status=202, request_model=SubmitMessageRequest,
                owned_conversation=True,
            ),
        }
        paths['/api/v1/conversations/{conversation_id}/jobs']['post']['responses']['409'] = self._response(
            ApiErrorResponse, 'The conversation is busy or interrupted.',
        )
        for suffix, method, name, description in (
            ('', 'get', 'getConversationJob', 'Return owned job status and its saved result.'),
            ('/events', 'get', 'streamConversationJob', 'Replay and follow owned job events. Disconnecting leaves the job running.'),
            ('/stop', 'post', 'stopConversationJob', 'Request cancellation and return the current status.'),
        ):
            streaming = suffix == '/events'
            operation = self._operation(
                name, description, ConversationJobDetail, owned_conversation=True, streaming=streaming,
            )
            operation['parameters'][0]['name'] = 'job_id'
            operation['responses']['404'] = self._response(ApiErrorResponse, 'Job unavailable.')
            if streaming:
                operation['parameters'].append({
                    'name': 'after', 'in': 'query',
                    'description': 'Replay events after this sequence number.',
                    'schema': {'type': 'integer', 'minimum': 0, 'default': 0},
                })
                operation['responses'].pop('409')
                operation['x-mosaic-sse'].update({
                    'framing': 'id: <sequence>\ndata: <ADK JSON record>\n\n',
                    'disconnect': 'Detach the subscriber; the job keeps running.',
                    'reconnection': 'Poll status or reconnect with the last received sequence.',
                    'errors': 'Check the job status for the completed outcome.',
                    'availability': 'Check the job status and conversation availability.',
                    'concurrency': 'Subscribers follow the same persisted job.',
                })
            paths[f'/api/v1/conversations/jobs/{{job_id}}{suffix}'] = {method: operation}
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
                '409': ['conversation_busy', 'conversation_interrupted'],
                '500': 'internal_error',
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
            'x-mosaic-implementation': (
                'available' if operation_id in self._implemented_operations else 'planned'
            ),
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
                ApiErrorResponse,
                'Conversation is reserved or interrupted; no new execution is dispatched. Interrupted history remains readable.',
            )
            operation['x-mosaic-sse'] = {
                'format': 'ADK',
                'framing': 'data: <ADK JSON record>\n\n',
                'text': 'Read content.parts[].text. Partial text is incremental; the final non-partial record repeats the full model turn.',
                'errors': 'Before streaming, return the HTTP error envelope; after streaming starts, emit {"error":"Invocation failed"}. EOF alone is not success.',
                'disconnect': 'Stop private execution. Do not reconstruct or resume an interrupted response.',
                'reconnection': 'Reload saved conversation history; no stream replay.',
                'privacy': 'Only the configured assistant text and answer metadata are relayed. No thoughts, signatures, tools, state or diagnostic details.',
                'availability': 'Use can_continue and is_interrupted from list/get. Interrupted conversations are read-only: disable input, show Interrupted — cannot continue, and offer a new conversation.',
                'concurrency': 'A conditional metadata reservation rejects overlapping public submissions. Existing reservations are never automatically reclaimed after a crash.',
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
                    'description': 'Server-generated correlation identifier shared with safe HTTP audit logs.',
                    'schema': {'type': 'string', 'format': 'uuid'},
                },
                'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}},
            },
            'content': {media_type: {'schema': schema}},
        }
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
