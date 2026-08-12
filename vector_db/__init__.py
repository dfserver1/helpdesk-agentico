"""
Vector DB package for HelpDesk Enterprise Copilot.
"""

from vector_db.chroma_store import (
    VectorStoreManager,
    vector_store_manager,
    get_vector_store,
    add_documents,
    similarity_search,
    delete_document_chunks,
    rebuild_index,
    get_collection_stats,
)

__all__ = [
    "VectorStoreManager",
    "vector_store_manager",
    "get_vector_store",
    "add_documents",
    "similarity_search",
    "delete_document_chunks",
    "rebuild_index",
    "get_collection_stats",
]