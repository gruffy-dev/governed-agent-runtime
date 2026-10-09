from typing import Literal

from fastapi import HTTPException


class AuthenticationError(HTTPException):
    def __init__(self, status_code: Literal[401, 403] = 401) -> None:
        """
        Identify a MOSAIC authentication denial for the shared error handler.

        :param status_code: Unauthorized or forbidden HTTP status.

        :raises ValueError: If the status is not an authentication denial.
        """
        if status_code not in {401, 403}:
            raise ValueError('Authentication status must be 401 or 403.')
        super().__init__(
            status_code=status_code,
            detail='Unauthorized' if status_code == 401 else 'Forbidden',
        )
