from fastapi import HTTPException, Request

from ...models.identity.trusted_request_configuration import TrustedRequestConfiguration
from ...models.identity.trusted_request_context import TrustedRequestContext
from ...models.identity.trusted_user_context import TrustedUserContext


class TrustedRequestContextDependency:
    def __init__(self, configuration: TrustedRequestConfiguration) -> None:
        """
        Bind API request identity to trusted server configuration.

        :param configuration: Application identity owned by the backend.
        """
        self._configuration = configuration

    async def __call__(self, request: Request) -> TrustedRequestContext:
        """
        Derive API identity exclusively from authentication middleware state.

        Caller-supplied application, user, workspace and ownership fields do
        not participate in identity resolution. Workspace services must use
        the returned user identifier to resolve ownership server-side.

        :param request: Request carrying middleware-validated user context.

        :return: Immutable application and user identity for API handlers.

        :raises HTTPException: If trusted authentication context is absent
            or is not a validated user context.
        """
        user_context = getattr(request.state, 'trusted_user_context', None)
        if not isinstance(user_context, TrustedUserContext):
            raise HTTPException(
                status_code=401,
                detail='Unauthorized',
                headers={
                    'Cache-Control': 'no-store',
                    'WWW-Authenticate': 'Bearer',
                },
            )
        return TrustedRequestContext(
            app_name=self._configuration.app_name,
            user_id=user_context.user_id,
        )
