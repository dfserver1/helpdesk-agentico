"""
Embeddings factory for HelpDesk Enterprise Copilot v12.
Supports Azure OpenAI embeddings and Google Gemini embeddings based on provider.
"""

from config.settings import get_settings
from config.logging import get_logger
from core.exceptions import ConfigurationError

logger = get_logger("embeddings")


def get_embeddings():
    """Return the configured embeddings instance based on LLM provider."""
    settings = get_settings()

    provider = settings.LLM_PROVIDER.lower()

    if provider == "azure_openai":
        return _get_azure_openai_embeddings(settings)
    elif provider == "google_gemini":
        return _get_google_embeddings(settings)
    else:
        raise ConfigurationError(
            f"Unknown LLM provider: {provider}. Use 'azure_openai' or 'google_gemini'."
        )


def _get_azure_openai_embeddings(settings):
    """Azure OpenAI embeddings (text-embedding-3-large)."""
    try:
        from langchain_openai import AzureOpenAIEmbeddings

        if not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_ENDPOINT:
            raise ConfigurationError(
                "Azure OpenAI API key and endpoint are not configured. "
                "Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env"
            )

        return AzureOpenAIEmbeddings(
            azure_deployment=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            chunk_size=100,
        )
    except ImportError:
        raise ConfigurationError(
            "Azure OpenAI embeddings require langchain-openai. Install: pip install langchain-openai"
        )
    except ConfigurationError:
        raise
    except Exception as e:
        raise ConfigurationError(f"Failed to initialize Azure OpenAI embeddings: {e}")


def _get_google_embeddings(settings):
    """Google Gemini embeddings (models/gemini-embedding-001)."""
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        if not settings.GOOGLE_API_KEY:
            raise ConfigurationError(
                "GOOGLE_API_KEY is not configured. Set it in .env"
            )

        return GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=settings.GOOGLE_API_KEY,
        )
    except ImportError:
        raise ConfigurationError(
            "Google Gemini embeddings require langchain-google-genai. "
            "Install: pip install langchain-google-genai"
        )
    except ConfigurationError:
        raise
    except Exception as e:
        raise ConfigurationError(f"Failed to initialize Google embeddings: {e}")


# Lazy-load a default embeddings instance.
_embeddings = None


def load_embeddings():
    """Initialize and cache the module-level embeddings instance."""
    global _embeddings
    if _embeddings is None:
        _embeddings = get_embeddings()
        logger.debug(f"Embeddings loaded (provider={get_settings().LLM_PROVIDER})")
    return _embeddings