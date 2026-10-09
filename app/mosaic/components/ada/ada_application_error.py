class AdaApplicationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """
        Represent a safe internal adapter failure without SDK response bodies.

        :param message: Adapter-owned explanation without upstream exception text.
        :param status_code: Optional HTTP status returned by the private application.
        """
        super().__init__(message)
        self.status_code = status_code
