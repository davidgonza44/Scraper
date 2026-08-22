"""Errors exposed by the Mercado Libre infrastructure adapter."""


class MercadoLibreError(RuntimeError):
    """Base error for failures produced by the Mercado Libre adapter."""


class MercadoLibreConfigurationError(MercadoLibreError):
    """Raised when required provider configuration is missing or invalid."""


class MercadoLibreConnectionError(MercadoLibreError):
    """Raised when connectivity or timeout retries are exhausted."""


class MercadoLibreResponseError(MercadoLibreError):
    """Base error for unusable successful API responses."""


class MercadoLibreInvalidJSONError(MercadoLibreResponseError):
    """Raised when the API response is not valid JSON."""


class MercadoLibreInvalidResponseError(MercadoLibreResponseError):
    """Raised when the API JSON does not follow the expected search structure."""


class MercadoLibreHTTPError(MercadoLibreError):
    """Raised for a non-recoverable HTTP response."""

    def __init__(self, status_code: int, message: str | None = None) -> None:
        self.status_code = status_code
        super().__init__(message or f"Mercado Libre request failed with HTTP {status_code}")


class MercadoLibreAuthenticationError(MercadoLibreHTTPError):
    """Raised for authentication or authorization failures."""

    def __init__(self, status_code: int) -> None:
        super().__init__(
            status_code,
            f"Mercado Libre authentication or authorization failed with HTTP {status_code}",
        )


class MercadoLibreRateLimitError(MercadoLibreHTTPError):
    """Raised when rate-limit retries are exhausted."""

    def __init__(self) -> None:
        super().__init__(429, "Mercado Libre rate limit retries were exhausted")
