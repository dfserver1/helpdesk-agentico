"""
Ensemble retriever: combines BM25 keyword search with dense vector search,
then applies Cross-Encoder reranking for the final top-K results.

Based on the ensemble strategy validated in ITOps best-practice repos:
  - BM25 (keyword)  = 40% weight
  - Vector (semantic) = 60% weight
  - CrossEncoder reranks top-10 down to top-3
"""

from pathlib import Path
from typing import List, Optional

import pandas as pd
from langchain_core.documents import Document

from config.settings import get_settings
from config.logging import get_logger
from rag.embeddings import load_embeddings
from core.exceptions import RAGError

logger = get_logger("retriever")


class EnsembleRetriever:
    """Hybrid retriever combining BM25 + FAISS with reranking."""

    def __init__(
        self,
        settings=None,
        k_initial: int = 10,
        k_final: int = 3,
        use_reranker: bool = True,
        tenant_id: Optional[int] = None,
    ):
        self.settings = settings or get_settings()
        self.k_initial = k_initial or self.settings.TOP_K_RESULTS
        self.k_final = k_final or self.settings.RERANK_TOP_K
        self.use_reranker = use_reranker and self.k_final < self.k_initial
        self.tenant_id = tenant_id
        self._retriever = None
        self._reranker = None
        self._corpus_docs: List[Document] = []

    # --- Retriever construction --------------------------------------------

    def _load_corpus(self, data_path: Optional[str] = None) -> List[Document]:
        """Load knowledge-base documents for BM25 from CSV/JSON/markdown."""
        # If a corpus file is configured, load it.
        corpus_file = data_path or getattr(self.settings, "CORPUS_PATH", None)
        if corpus_file and Path(corpus_file).exists():
            from utils.document_processor import processor

            processed = processor.process(corpus_file)
            return processed.chunks

        # Fallback: empty corpus (vector store alone drives retrieval)
        return []

    def build_ensemble(
        self,
        vectorstore,
        corpus_docs: Optional[List[Document]] = None,
        data_path: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ):
        """
        Build the hybrid EnsembleRetriever.

        Args:
            vectorstore: A LangChain VectorStore with an `as_retriever` method.
            corpus_docs: Optional list of docs for BM25 retrieval.
            data_path: Optional path to corpus for BM25.
            tenant_id: Optional tenant scope. When present, vector search is
                filtered by ``tenant_id`` so retrieval never leaks across
                organizations.
        """
        try:
            from langchain_community.retrievers import BM25Retriever
            # langchain >= 1.x moved EnsembleRetriever into the classic shim
            try:
                from langchain.retrievers import EnsembleRetriever
            except ImportError:
                from langchain_classic.retrievers.ensemble import EnsembleRetriever

            self.tenant_id = tenant_id or self.tenant_id
            self._corpus_docs = corpus_docs or self._load_corpus(data_path)

            retrievers = []
            weights = []

            # Vector retriever (optional: absent in BM25-only fallback mode)
            if vectorstore is not None:
                search_kwargs = {"k": self.k_initial}
                if self.tenant_id is not None:
                    search_kwargs["filter"] = {"tenant_id": str(self.tenant_id)}
                vector_retriever = vectorstore.as_retriever(
                    search_kwargs=search_kwargs
                )
                retrievers.append(vector_retriever)
                weights.append(self.settings.ENSEMBLE_VECTOR_WEIGHT)

            # BM25 retriever if we have corpus documents
            if self._corpus_docs:
                bm25 = BM25Retriever.from_documents(
                    self._corpus_docs, k=self.k_initial
                )
                retrievers.insert(0, bm25)
                weights.insert(0, self.settings.ENSEMBLE_BM25_WEIGHT)

            if not retrievers:
                raise RAGError(
                    "No retrievers available. Provide a vector store and/or "
                    "a BM25 corpus (memory/knowledge base)."
                )

            self._retriever = EnsembleRetriever(
                retrievers=retrievers,
                weights=weights,
            )
            logger.debug("Ensemble retriever built: BM25+Vector")
            return self._retriever
        except ImportError as e:
            raise RAGError(f"Ensemble retrieval dependencies missing: {e}")
        except Exception as e:
            raise RAGError(f"Failed to build ensemble retriever: {e}")

    # --- Reranker ---------------------------------------------------------
    def _get_reranker(self):
        """Lazy-load CrossEncoder reranker."""
        if self._reranker is None:
            try:
                from langchain_community.cross_encoders import HuggingFaceCrossEncoder
            except ImportError:
                from langchain.embeddings import HuggingFaceEmbeddings  # noqa: F401

            try:
                from langchain.retrievers.document_compressors import CrossEncoderReranker
            except ImportError:
                from langchain_classic.retrievers.document_compressors import (
                    CrossEncoderReranker,
                )

            try:
                cross_encoder = HuggingFaceCrossEncoder(
                    model_name=self.settings.RERANKER_MODEL
                )
                self._reranker = CrossEncoderReranker(
                    model=cross_encoder,
                    top_n=self.k_final,
                )
                logger.debug(f"Reranker loaded: {self.settings.RERANKER_MODEL}")
            except Exception as e:
                logger.warning(f"Reranker unavailable, skipping: {e}")
                self._reranker = None
        return self._reranker

    # --- Query ------------------------------------------------------------
    def retrieve(self, query: str, filter_metadata: Optional[dict] = None) -> List[Document]:
        """
        Run ensemble retrieval + optional reranking.

        Returns:
            Top documents with relevance_score metadata.
        """
        if self._retriever is None:
            raise RAGError("Retriever not built. Call build_ensemble() first.")

        try:
            # Initial ensemble retrieval
            docs = self._retriever.invoke(query)

            # Rerank if enabled
            if self.use_reranker:
                reranker = self._get_reranker()
                if reranker is not None:
                    try:
                        docs = reranker.compress_documents(docs, query=query)
                    except Exception as e:
                        logger.warning(
                            f"Reranking unavailable for query, using ensemble order: {e}"
                        )

            # Normalize relevance scores for non-vector docs
            for i, doc in enumerate(docs):
                if "relevance_score" not in doc.metadata:
                    doc.metadata["relevance_score"] = 1.0 / (i + 1)

            logger.debug(f"Retrieved {len(docs)} docs for query")
            return docs
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            raise RAGError(f"Retrieval failed: {e}")


# --- Module-level singleton ------------------------------------------------
_retriever_instance = None


def get_ensemble_retriever(vectorstore=None, corpus_docs=None, tenant_id=None) -> EnsembleRetriever:
    """Get (and cache) the ensemble retriever instance."""
    global _retriever_instance
    if _retriever_instance is None:
        if vectorstore is None:
            # Load the default vector store and build the retriever
            from vector_db.chroma_store import get_vector_store
            vectorstore = get_vector_store()
        _retriever_instance = EnsembleRetriever(tenant_id=tenant_id)
        _retriever_instance.build_ensemble(vectorstore, corpus_docs)
    return _retriever_instance