import json
import logging

from ...models.identity.trusted_request_context import TrustedRequestContext


class TrustedIdentityAudit:
    def __init__(self) -> None:
        """
        Bind identity resolution events to a dedicated allowlisted logger.
        """
        self._logger = logging.getLogger('mosaic.identity')

    def resolved(self, context: TrustedRequestContext) -> None:
        """
        Record derived identity without request fields or credential material.

        :param context: Immutable server-derived application and user identity.
        """
        metadata = {
            'mosaic_event': 'trusted_identity_resolved',
            'app_name': context.app_name,
            'user_id': context.user_id,
        }
        self._logger.info(
            'MOSAIC trusted identity %s',
            json.dumps(metadata, sort_keys=True),
            extra=metadata,
        )
