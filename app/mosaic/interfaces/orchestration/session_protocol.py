from typing import Protocol


class SessionProtocol(Protocol):
    id: str
    app_name: str
    user_id: str
