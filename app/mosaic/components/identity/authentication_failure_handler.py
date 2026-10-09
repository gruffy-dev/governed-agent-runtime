import json
import logging
from typing import Any, Literal
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from .authentication_error import AuthenticationError
from ...models.identity.authentication_error_response import AuthenticationErrorResponse


class AuthenticationFailureHandler:
    def __init__(self) -> None:
        """
        Bind authentication failure logging to its dedicated safe logger.
        """
        self._logger = logging.getLogger('mosaic.authentication')

    def register(self, application: Any) -> None:
        """
        Register only the MOSAIC authentication exception handler.

        :param application: FastAPI-compatible application receiving handlers.
        """
        application.add_exception_handler(
            AuthenticationError,
            self.handle_exception,
        )

    async def handle_exception(
        self,
        request: Request,
        exception: AuthenticationError,
    ) -> JSONResponse:
        """
        Convert a MOSAIC authentication denial into its public response.

        :param request: Request excluded from failure logging.
        :param exception: Authentication denial carrying only its HTTP status.

        :return: Correlated generic authentication failure response.

        :raises ValueError: If the exception has an unsupported status.
        """
        if exception.status_code == 401:
            return self.create_response(401)
        if exception.status_code == 403:
            return self.create_response(403)
        raise ValueError('Authentication status must be 401 or 403.')

    def create_response(
        self,
        status_code: Literal[401, 403],
    ) -> JSONResponse:
        """
        Log allowlisted failure metadata and return the matching envelope.

        Generate correlation identifiers server-side. Never read or log
        request headers, cookies, paths, bodies, tokens or token hashes.

        :param status_code: Unauthorized or forbidden HTTP status.

        :return: No-store error with matching body and header correlation IDs.

        :raises ValueError: If the status is not an authentication denial.
        """
        if status_code not in {401, 403}:
            raise ValueError('Authentication status must be 401 or 403.')
        unauthorized = status_code == 401
        envelope = AuthenticationErrorResponse(
            detail='Unauthorized' if unauthorized else 'Forbidden',
            error_code='unauthorized' if unauthorized else 'forbidden',
            action=(
                'Sign in again or supply a valid bearer token.'
                if unauthorized
                else 'Contact the administrator to check your access.'
            ),
            correlation_id=uuid4(),
        )
        metadata = {
            'mosaic_event': 'authentication_rejected',
            'status_code': status_code,
            'error_code': envelope.error_code,
            'correlation_id': str(envelope.correlation_id),
        }
        self._logger.warning(
            'MOSAIC authentication failure %s',
            json.dumps(metadata, sort_keys=True),
            extra=metadata,
        )
        headers = {
            'Cache-Control': 'no-store',
            'X-Correlation-ID': str(envelope.correlation_id),
        }
        if unauthorized:
            headers['WWW-Authenticate'] = 'Bearer'
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode='json'),
            headers=headers,
        )
