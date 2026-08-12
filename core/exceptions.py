"""
Core exceptions for HelpDesk Enterprise Copilot v12.
"""

from typing import Any, Dict, Optional


class HelpDeskException(Exception):
    """Base exception for all HelpDesk errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class ConfigurationError(HelpDeskException):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "CONFIGURATION_ERROR", 500, details)


class AuthenticationError(HelpDeskException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "AUTHENTICATION_ERROR", 401, details)


class AuthorizationError(HelpDeskException):
    """Raised when authorization fails."""

    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "AUTHORIZATION_ERROR", 403, details)


class ValidationError(HelpDeskException):
    """Raised when input validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "VALIDATION_ERROR", 400, details)


class NotFoundError(HelpDeskException):
    """Raised when a resource is not found."""

    def __init__(self, message: str = "Resource not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "NOT_FOUND", 404, details)


class RAGError(HelpDeskException):
    """Raised when RAG pipeline fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "RAG_ERROR", 500, details)


class VectorStoreError(HelpDeskException):
    """Raised when vector store operations fail."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "VECTOR_STORE_ERROR", 500, details)


class SLAError(HelpDeskException):
    """Raised when SLA engine fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "SLA_ERROR", 500, details)


class AgentError(HelpDeskException):
    """Raised when agent execution fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "AGENT_ERROR", 500, details)


class MemoryError(HelpDeskException):
    """Raised when memory operations fail."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "MEMORY_ERROR", 500, details)


class RateLimitError(HelpDeskException):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, "RATE_LIMIT_EXCEEDED", 429, {"retry_after": retry_after})


class DocumentProcessingError(HelpDeskException):
    """Raised when document processing fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "DOCUMENT_PROCESSING_ERROR", 500, details)


class ExternalServiceError(HelpDeskException):
    """Raised when external service calls fail."""

    def __init__(self, message: str, service: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "EXTERNAL_SERVICE_ERROR", 502, {"service": service, **(details or {})})


class SelfTrainingError(HelpDeskException):
    """Raised when self-training pipeline fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "SELF_TRAINING_ERROR", 500, details)