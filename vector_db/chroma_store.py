"""
Vector store manager using ChromaDB for RAG retrieval.
Provides add, search, delete, rebuild, and stats operations.
"""

import os
from pathlib import Path
from typing import List, Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document

from config.settings import get_settings
from config.logging import get_logger
from core.exceptions import VectorStoreError
from rag.embeddings import get_embeddings

logger = get_logger("vector_store")


class VectorStoreManager:
    """ChromaDB-backed vector store manager."""

    def __init__(self, settings=None, collection_name: str = None):
        self.settings = settings or get_settings()
        self.collection_name = collection_name or self.settings.CHROMA_COLLECTION_NAME
        self.chroma_client = None
        self._vectorstore = None

    def _ensure_client(self):
        """Ensure ChromaDB client is created."""
        if self.chroma_client is None:
            import chromadb

            persist_dir = Path(self.settings.CHROMA_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)
            try:
                self.chroma_client = (
                    chromadb.PersistentClient(path=str(persist_dir))
                    if self.settings.CHROMA_PERSIST_DIR
                    else chromadb.Client()
                )
                logger.debug(f"ChromaDB client initialized at {persist_dir}")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                raise VectorStoreError(f"Failed to initialize ChromaDB: {e}")

    def get_vector_store(self) -> Chroma:
        """Get (or create) the LangChain Chroma wrapper."""
        self._ensure_client()
        if self._vectorstore is None:
            try:
                self._vectorstore = Chroma(
                    client=self.chroma_client,
                    collection_name=self.collection_name,
                    embedding_function=get_embeddings(),
                )
                logger.debug(f"Vector store ready (collection='{self.collection_name}')")
            except Exception as e:
                logger.error(f"Failed to create vector store: {e}")
                raise VectorStoreError(f"Failed to create vector store: {e}")
        return self._vectorstore

    def add_documents(self, documents: List[Document], tenant_id: int) -> int:
        """
        Index documents into the vector store.

        Args:
            documents: Chunked documents with metadata.
            tenant_id: Tenant scope.

        Returns:
            Number of chunks indexed.
        """
        if not documents:
            logger.warning("No documents to index")
            return 0

        for doc in documents:
            doc.metadata.setdefault("tenant_id", str(tenant_id))

        try:
            vector_store = self.get_vector_store()
            vector_store.add_documents(documents)
            logger.info(f"Indexed {len(documents)} chunks for tenant {tenant_id}")
            return len(documents)
        except Exception as e:
            logger.error(f"Failed to index documents: {e}")
            raise VectorStoreError(f"Failed to index documents: {e}")

    def similarity_search(
        self,
        query: str,
        tenant_id: Optional[int] = None,
        k: int = None,
        score_threshold: Optional[float] = None,
    ) -> List[Document]:
        """
        Semantic similarity search with optional tenant/metadata filters.

        Args:
            query: User question.
            tenant_id: Filter to a tenant.
            k: Number of results.
            score_threshold: Minimum relevance.

        Returns:
            List of Document objects with relevance_score metadata.
        """
        k = k or self.settings.TOP_K_RESULTS
        vector_store = self.get_vector_store()

        try:
            if tenant_id is not None:
                # Tenant-scoped filtering using where
                results = vector_store.similarity_search_with_relevance_scores(
                    query, k=k, filter={"tenant_id": str(tenant_id)}
                )
            else:
                results = vector_store.similarity_search_with_relevance_scores(query, k=k)

            docs = []
            for doc, score in results:
                if score_threshold is not None and score < score_threshold:
                    continue
                doc.metadata["relevance_score"] = round(float(score), 4)
                docs.append(doc)
            logger.debug(f"Similarity search returned {len(docs)} results")
            return docs
        except Exception as e:
            logger.exception(f"Similarity search failed: {e}")
            raise VectorStoreError(f"Similarity search failed: {e}")

    def delete_document_chunks(self, document_id: str, tenant_id: int) -> bool:
        """Delete all chunks for a document, scoped to the tenant."""
        try:
            self._ensure_client()
            client = self.chroma_client
            if client is None:
                return False

            collection = client.get_collection(self.collection_name)
            collection.delete(
                where={
                    "document_id": str(document_id),
                    "tenant_id": str(tenant_id),
                }
            )
            logger.info(f"Deleted chunks for document {document_id} (tenant {tenant_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document chunks: {e}")
            return False

    def rebuild_index(self, all_chunks: List[Document]) -> int:
        """Replace the index for a single tenant without touching other tenants.

        Chunks are expected to carry a ``tenant_id`` in metadata; only that
        tenant's vectors are removed and re-added, leaving every other
        organization's index intact.
        """
        if not all_chunks:
            return 0

        tenant_id = all_chunks[0].metadata.get("tenant_id", "1")
        try:
            self._ensure_client()
            client = self.chroma_client
            if client is not None:
                collection = client.get_collection(self.collection_name)
                collection.delete(where={"tenant_id": str(tenant_id)})
                logger.info(f"Cleared vectors for tenant {tenant_id} before rebuild")
            self._vectorstore = None  # Force reinitialize the wrapper
        except Exception as e:
            logger.warning(f"Could not clear tenant vectors (may not exist): {e}")

        return self.add_documents(all_chunks, tenant_id=tenant_id)

    def get_collection_stats(self) -> dict:
        """Return stats about the vector store."""
        try:
            self._ensure_client()
            if self.chroma_client is None:
                return {"total_chunks": 0}

            collections = self.chroma_client.list_collections()
            for col in collections:
                if col.name == self.collection_name:
                    return {"total_chunks": col.count()}
            return {"total_chunks": 0}
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {"total_chunks": 0}


vector_store_manager = VectorStoreManager()


def get_vector_store() -> Chroma:
    return vector_store_manager.get_vector_store()


def add_documents(documents: List[Document], tenant_id: int) -> int:
    return vector_store_manager.add_documents(documents, tenant_id)


def similarity_search(query: str, tenant_id: int = None, k: int = None) -> List[Document]:
    return vector_store_manager.similarity_search(query, tenant_id=tenant_id, k=k)


def delete_document_chunks(document_id: str, tenant_id: int) -> bool:
    return vector_store_manager.delete_document_chunks(document_id, tenant_id)


def rebuild_index(all_chunks: List[Document]) -> int:
    return vector_store_manager.rebuild_index(all_chunks)


def get_collection_stats() -> dict:
    return vector_store_manager.get_collection_stats()