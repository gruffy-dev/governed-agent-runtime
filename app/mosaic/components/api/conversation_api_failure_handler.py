import json
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .conversation_not_found_error import ConversationNotFoundError
from ..ada.ada_application_error import AdaApplicationError
from ...models.api.api_error_response import ApiErrorResponse


class ConversationApiFailureHandler:
    def __init__(self) -> None:
        """
        Bind public API failure events to a payload-free logger.
        """
        self._logger = logging.getLogger('mosaic.conversation')

    def register(self, application: FastAPI) -> None:
        """
        Register safe conversation errors without changing authentication errors.

        :param application: Public MOSAIC app receiving exception handlers.
        """
        for error in (
            ConversationNotFoundError,
            AdaApplicationError,
            SQLAlchemyError,
            Exception,
        ):
            application.add_exception_handler(error, self.handle_failure)
        application.add_exception_handler(
            RequestValidationError, self.handle_validation
        )

    async def handle_failure(self, request: Request, error: Exception) -> JSONResponse:
        """
        Return a non-disclosing conversation failure without exception text.

        :param request: Request excluded from logging.
        :param error: Typed failure used only to choose missing or internal status.

        :return: Correlated no-store 404 or 500 response.
        """
        return self._response(
            404 if isinstance(error, ConversationNotFoundError) else 500
        )

    async def handle_validation(
        self,
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        """
        Hide submitted values in conversation validation responses.

        :param request: Request used only to select the conversation route family.
        :param error: Framework validation error never logged or echoed by this API.

        :return: Safe 400 for conversation routes; normal validation elsewhere.
        """
        if request.url.path == '/api/v1/conversations' or request.url.path.startswith(
            '/api/v1/conversations/'
        ):
            return self._response(400)
        return await request_validation_exception_handler(request, error)

    def _response(self, status_code: int) -> JSONResponse:
        """
        Log allowlisted failure metadata and produce the matching public envelope.

        :param status_code: Internal selected validation, missing or failure status.

        :return: Response with matching body, log and header correlation ID.
        """
        detail, code, action = {
            400: (
                'Invalid request',
                'invalid_request',
                'Check the request format and try again.',
            ),
            404: (
                'Conversation unavailable',
                'conversation_not_found',
                'Choose an available conversation.',
            ),
            500: (
                'Request failed',
                'internal_error',
                'Try again or contact the administrator.',
            ),
        }[status_code]
        envelope = ApiErrorResponse(
            detail=detail, error_code=code, action=action, correlation_id=uuid4()
        )
        metadata = {
            'mosaic_event': 'conversation_request_rejected',
            'status_code': status_code,
            'error_code': code,
            'correlation_id': str(envelope.correlation_id),
        }
        self._logger.warning(
            'MOSAIC conversation failure %s',
            json.dumps(metadata, sort_keys=True),
            extra=metadata,
        )
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode='json'),
            headers={
                'Cache-Control': 'no-store',
                'X-Correlation-ID': str(envelope.correlation_id),
            },
        )
