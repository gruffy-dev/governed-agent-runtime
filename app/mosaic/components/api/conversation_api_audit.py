import json
import logging
from typing import Literal
from uuid import UUID, uuid4

from ...models.identity.trusted_request_context import TrustedRequestContext


class ConversationApiAudit:
    def __init__(self) -> None:
        """
        Bind successful conversation requests to an allowlisted audit logger.
        """
        self._logger = logging.getLogger('mosaic.conversation')

    def completed(
        self,
        context: TrustedRequestContext,
        operation: Literal['create', 'list', 'get', 'submit'],
        status_code: int,
    ) -> UUID:
        """
        Record successful HTTP setup without paths, text or credentials.

        For submit, HTTP success means streaming has started, not that the model
        invocation has completed successfully.

        :param context: Server-derived application and user identity.
        :param operation: Backend-selected lifecycle operation name.
        :param status_code: Successful HTTP status selected by the handler.

        :return: Server-generated correlation ID for the success response header.
        """
        correlation_id = uuid4()
        metadata = {
            'mosaic_event': 'conversation_request_completed',
            'app_name': context.app_name,
            'user_id': context.user_id,
            'operation': operation,
            'status_code': status_code,
            'correlation_id': str(correlation_id),
        }
        self._logger.info(
            'MOSAIC conversation request %s',
            json.dumps(metadata, sort_keys=True),
            extra=metadata,
        )
        return correlation_id
