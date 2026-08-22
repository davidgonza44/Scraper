"""AI infrastructure adapters."""

from bera_price_tracker.infrastructure.ai.ollama import (
    OLLAMA_CLASSIFICATION_PROMPT_VERSION,
    OLLAMA_SYSTEM_PROMPT,
    OllamaAIProductClassifier,
    OllamaConnectionError,
    OllamaHTTPError,
    OllamaInvalidResponseError,
    OllamaModelUnavailableError,
    OllamaTimeoutError,
)

__all__ = [
    "OLLAMA_CLASSIFICATION_PROMPT_VERSION",
    "OLLAMA_SYSTEM_PROMPT",
    "OllamaAIProductClassifier",
    "OllamaConnectionError",
    "OllamaHTTPError",
    "OllamaInvalidResponseError",
    "OllamaModelUnavailableError",
    "OllamaTimeoutError",
]
