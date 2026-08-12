"""
LLM factory for HelpDesk Enterprise Copilot v12.
Supports Azure OpenAI and Google Gemini chat models.
"""

from config.settings import get_settings
from config.logging import get_logger
from core.exceptions import ConfigurationError

logger = get_logger("llm")


def get_chat_llm(temperature: float = 0.0, max_tokens: int = 2048):
    """Return the configured chat LLM based on provider."""
    settings = get_settings()
    provider = settings.LLM_PROVIDER.lower()

    if provider == "azure_openai":
        return _get_azure_openai_llm(settings, temperature, max_tokens)
    elif provider == "google_gemini":
        return _get_google_llm(settings, temperature, max_tokens)
    else:
        raise ConfigurationError(
            f"Unknown LLM provider: {provider}. Use 'azure_openai' or 'google_gemini'."
        )


def _get_azure_openai_llm(settings, temperature, max_tokens):
    """Azure OpenAI chat model (gpt-4o / o1)."""
    try:
        from langchain_openai import AzureChatOpenAI

        if not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_ENDPOINT:
            raise ConfigurationError(
                "Azure OpenAI API key and endpoint are not configured. "
                "Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env"
            )

        return AzureChatOpenAI(
            azure_deployment=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ImportError:
        raise ConfigurationError(
            "Azure OpenAI LLM requires langchain-openai. Install: pip install langchain-openai"
        )
    except ConfigurationError:
        raise
    except Exception as e:
        raise ConfigurationError(f"Failed to initialize Azure OpenAI LLM: {e}")


def _get_google_llm(settings, temperature, max_tokens):
    """Google Gemini chat model."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not settings.GOOGLE_API_KEY:
            raise ConfigurationError(
                "GOOGLE_API_KEY is not configured. Set it in .env"
            )

        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    except ImportError:
        raise ConfigurationError(
            "Google Gemini LLM requires langchain-google-genai. "
            "Install: pip install langchain-google-genai"
        )
    except ConfigurationError:
        raise
    except Exception as e:
        raise ConfigurationError(f"Failed to initialize Google Gemini LLM: {e}")


# Default instance cache
_llm = None


def load_llm(temperature: float = 0.0):
    """Initialize and cache a default chat LLM instance."""
    global _llm
    if _llm is None:
        _llm = get_chat_llm(temperature=temperature)
    return _llm