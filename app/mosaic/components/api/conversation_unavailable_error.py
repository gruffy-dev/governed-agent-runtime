class ConversationUnavailableError(RuntimeError):
    def __init__(self, *, is_interrupted: bool) -> None:
        """
        Reject a reserved or interrupted conversation without exposing SDK state.

        :param is_interrupted: Whether a stopped invocation made the conversation read-only.
        """
        self.is_interrupted = is_interrupted
        super().__init__('Conversation cannot accept another message.')
