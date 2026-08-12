"""
RAG package for HelpDesk Enterprise Copilot.
"""

from rag.embeddings import get_embeddings, load_embeddings
from rag.llm import get_chat_llm, load_llm
from rag.retriever import EnsembleRetriever, get_ensemble_retriever
from rag.pipeline import (
    RAGPipeline,
    RAGResult,
    SourceCitation,
    get_rag_pipeline,
    build_context,
    parse_llm_response,
    rewrite_query,
)

__all__ = [
    "get_embeddings",
    "load_embeddings",
    "get_chat_llm",
    "load_llm",
    "EnsembleRetriever",
    "get_ensemble_retriever",
    "RAGPipeline",
    "RAGResult",
    "SourceCitation",
    "get_rag_pipeline",
    "build_context",
    "parse_llm_response",
    "rewrite_query",
]