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
from bera_price_tracker.infrastructure.ai.ollama_negotiation import (
    OLLAMA_NEGOTIATION_PROMPT_VERSION,
    OLLAMA_NEGOTIATION_SYSTEM_PROMPT,
    OllamaAlibabaNegotiationDrafter,
)

__all__ = [
    "OLLAMA_CLASSIFICATION_PROMPT_VERSION",
    "OLLAMA_NEGOTIATION_PROMPT_VERSION",
    "OLLAMA_NEGOTIATION_SYSTEM_PROMPT",
    "OLLAMA_SYSTEM_PROMPT",
    "OllamaAIProductClassifier",
    "OllamaAlibabaNegotiationDrafter",
    "OllamaConnectionError",
    "OllamaHTTPError",
    "OllamaInvalidResponseError",
    "OllamaModelUnavailableError",
    "OllamaTimeoutError",
]
