"""
Configuration management for HelpDesk Enterprise Copilot.
Uses Pydantic Settings for type-safe environment variable loading.
"""

from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "HelpDesk Enterprise Copilot"
    APP_VERSION: str = "12.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # --- LLM Provider ---
    LLM_PROVIDER: str = "azure_openai"

    # --- Azure OpenAI ---
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-large"
    AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = 3072

    # --- Google Gemini ---
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"

    # --- JWT Auth ---
    JWT_SECRET_KEY: str = ""

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _validate_jwt_secret(cls, v):
        # An empty secret is only allowed for local dev: it gets replaced by an
        # ephemeral per-process value in the model validator below. Production
        # and staging must provide a real, strong secret.
        if v and len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return v

    @model_validator(mode="after")
    def _resolve_ephemeral_secret(self):
        if not self.JWT_SECRET_KEY:
            if self.is_production:
                raise ValueError(
                    "JWT_SECRET_KEY is required in production. Set a strong secret."
                )
            import secrets

            self.JWT_SECRET_KEY = secrets.token_urlsafe(48)
        return self

    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Entra ID (Azure AD) ---
    ENTRA_ID_TENANT_ID: str = ""
    ENTRA_ID_CLIENT_ID: str = ""
    ENTRA_ID_CLIENT_SECRET: str = ""
    ENTRA_ID_AUTHORITY: str = ""
    ENTRA_ID_SCOPE: str = "https://graph.microsoft.com/.default"

    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./helpdesk.db"

    # --- ChromaDB ---
    CHROMA_PERSIST_DIR: str = "./data/chroma_store"
    CHROMA_COLLECTION_NAME: str = "helpdesk_docs"
    CHROMA_DISTANCE_FUNCTION: str = "cosine"

    # --- FAISS ---
    FAISS_INDEX_PATH: str = "./data/faiss_index"

    # --- FastAPI ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = True
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:8501", "http://localhost:3000"])

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.strip("[]").split(",")]
        return v

    # --- File Upload ---
    UPLOAD_DIR: str = "./data/uploads"
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: List[str] = Field(default_factory=lambda: ["pdf", "docx", "txt", "md"])

    @field_validator("ALLOWED_EXTENSIONS", mode="before")
    @classmethod
    def parse_allowed_extensions(cls, v):
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",")]
        return v

    # --- RAG Settings ---
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K_RESULTS: int = 10
    RERANK_TOP_K: int = 3
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ENSEMBLE_BM25_WEIGHT: float = 0.4
    ENSEMBLE_VECTOR_WEIGHT: float = 0.6
    SIMILARITY_THRESHOLD: float = 0.25

    # --- SLA Settings ---
    SLA_P1_RESPONSE_MINUTES: int = 0
    SLA_P2_RESPONSE_HOURS: int = 4
    SLA_P3_RESPONSE_HOURS: int = 24
    SLA_P4_RESPONSE_HOURS: int = 72
    SLA_ESCALATION_MULTIPLIER: float = 2.0
    SLA_BUSINESS_HOURS_START: int = 9
    SLA_BUSINESS_HOURS_END: int = 18
    SLA_TIMEZONE: str = "UTC"

    # --- Rate Limiting ---
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # --- Admin bootstrap (provisioned at startup, not hardcoded credentials) ---
    ADMIN_EMAIL: str = "admin@helpdesk.ai"
    ADMIN_PASSWORD: str = ""

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"
    LOG_FORMAT: str = "json"

    # --- LangSmith ---
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "helpdesk-copilot"

    # --- Langfuse ---
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # --- Celery / Redis ---
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # --- Memory / Self-Training ---
    MEMORY_STORE_TYPE: str = "postgresql"
    MEMORY_MAX_HISTORY: int = 50
    MEMORY_EMBEDDING_DIMENSIONS: int = 3072
    SELF_TRAINING_ENABLED: bool = True
    SELF_TRAINING_BATCH_SIZE: int = 100
    SELF_TRAINING_MIN_CONFIDENCE: float = 0.8

    # --- Concurrency / Multithreading ---
    MAX_CONCURRENT_SESSIONS: int = 8          # cap on parallel agent runs
    CHAT_EXECUTOR_THREADS: int = 8            # worker threads for blocking LLM/retrieval
    SUBTASK_MAX_WORKERS: int = 4              # parallel sub-agent workers
    SUBTASK_ENABLED: bool = True              # enable heavy-task decomposition
    AGENT_STREAMING: bool = False

    # --- O365 Connectors (Microsoft Graph) ---
    CONNECTORS_ENABLED: bool = False
    GRAPH_TENANT_ID: str = ""
    GRAPH_CLIENT_ID: str = ""
    GRAPH_CLIENT_SECRET: str = ""
    SKIP_PROVIDER_CERT_VALIDATION: bool = False
    SHAREPOINT_ENABLED: bool = True
    TEAMS_ENABLED: bool = True
    OUTLOOK_ENABLED: bool = True
    CONNECTOR_MAX_RESULTS: int = 8

    # --- Ticket backend (ITSM integration) ---
    # database | freshservice
    TICKET_BACKEND: str = "database"
    # Freshservice (used when TICKET_BACKEND=freshservice)
    FRESHSERVICE_BASE_URL: str = ""
    FRESHSERVICE_API_KEY: str = ""
    FRESHSERVICE_API_KEY_ID: str = ""
    # Jira (used when TICKET_BACKEND=jira)
    JIRA_BASE_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_PROJECT_KEY: str = "HELPDESK"

    # --- Web Search fallback (when no internal docs) ---
    WEB_SEARCH_ENABLED: bool = True
    WEB_SEARCH_MAX_RESULTS: int = 5
    WEB_SEARCH_TIMEOUT_SECONDS: int = 12
    # Optional API keys for richer web search (free tiers). If empty, the
    # pipeline uses DuckDuckGo's anonymous results + Wikipedia API.
    TAVILY_API_KEY: str = ""
    BRAVE_SEARCH_KEY: str = ""

    # --- OAuth (Google / Microsoft 365) ---
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    MICROSOFT_OAUTH_CLIENT_ID: str = ""
    MICROSOFT_OAUTH_CLIENT_SECRET: str = ""
    MICROSOFT_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/microsoft/callback"
    OAUTH_SESSION_TTL_HOURS: int = 12

    # --- Computed Properties ---
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    @property
    def sla_response_times(self) -> dict:
        return {
            "P1": self.SLA_P1_RESPONSE_MINUTES * 60,
            "P2": self.SLA_P2_RESPONSE_HOURS * 3600,
            "P3": self.SLA_P3_RESPONSE_HOURS * 3600,
            "P4": self.SLA_P4_RESPONSE_HOURS * 3600,
        }

    @property
    def ensemble_weights(self) -> list:
        return [self.ENSEMBLE_BM25_WEIGHT, self.ENSEMBLE_VECTOR_WEIGHT]


@lru_cache()
def get_settings() -> Settings:
    return Settings()