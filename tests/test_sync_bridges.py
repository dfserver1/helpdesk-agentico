"""
Regression tests for the fixed sync/async bridges and RAG pipeline glue.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Use a clean temp DB for memory sync-bridge tests
_db = Path(tempfile.gettempdir()) / "hdtest_sync.db"
_db.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(_db)
os.environ["JWT_SECRET_KEY"] = "test-secret-key-please-change"
os.environ["LOG_LEVEL"] = "ERROR"

from database.models import init_db  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _db_init():
    import asyncio

    asyncio.run(init_db())
    yield
    _db.unlink(missing_ok=True)


def test_sync_memory_facades():
    """The sync facades must run without an event loop and persist."""
    from services.memory_service import MemoryService

    svc = MemoryService()

    entry = svc.add_episodic_memory_sync(
        tenant_id=1,
        content="Rebuild the OU tree to push the GPO again.",
        source_query="GPO not applying to laptops",
        metadata={"category": "AD"},
        confidence=0.9,
    )
    assert entry.id > 0

    docs = svc.get_retrieval_documents_sync(tenant_id=1)
    assert isinstance(docs, list)
    assert len(docs) >= 1
    assert any("GPO not applying to laptops" in d.page_content for d in docs)

    used, ctx = svc.get_relevant_context_sync(1, "laptops GPO not applying")
    assert used is True
    assert ctx and "GPO" in ctx


def test_sync_facades_inside_running_loop():
    """Sync facades must also work when called from within an async loop."""
    import asyncio

    from services.memory_service import MemoryService

    async def _inner():
        svc = MemoryService()
        entry = svc.add_episodic_memory_sync(
            tenant_id=1,
            content="Rotate the TLS certificates in KMS vault.",
            source_query="expiring cert warning",
        )
        return entry.id

    mem_id = asyncio.run(_inner())
    assert mem_id > 0


def test_build_context_handles_dicts_and_docs():
    from rag.pipeline import build_context

    dict_docs = [
        {"document_name": "runbook-a", "chunk_text": "Reboot the spooler", "relevance_score": 0.9},
        {"document_name": "runbook-b", "chunk_text": "Clear the queue", "relevance_score": 0.7},
    ]
    ctx = build_context(dict_docs)
    assert "Reboot the spooler" in ctx
    assert "[Source 1: runbook-a" in ctx

    from langchain_core.documents import Document

    doc_docs = [
        Document(
            page_content="NTP sync steps",
            metadata={"source": "kb.md", "page": 3, "relevance_score": 0.8},
        )
    ]
    ctx_docs = build_context(doc_docs)
    assert "NTP sync steps" in ctx_docs
    assert "kb.md" in ctx_docs


def test_answer_template_format_keys():
    """RAG_ANSWER_TEMPLATE must format with the exact placeholders used."""
    from rag.pipeline import RAG_ANSWER_TEMPLATE

    prompt = RAG_ANSWER_TEMPLATE.format(
        company="HelpDesk Enterprise Copilot",
        context="context here",
        question="q?",
        chat_history="",
        language="en",
    )
    assert "Helpdesk Enterprise Copilot".lower() in prompt.lower()
    assert "context here" in prompt


def test_agent_graph_builds_with_checkpointer():
    """The graph must compile with the checkpointer and resume support."""
    from agent.graph import build_agent

    graph = build_agent()
    nodes = set(graph.get_graph().nodes)
    expected = {
        "classify", "retrieve", "grade", "rewrite",
        "generate_answer", "draft", "approval_gate",
        "create_ticket", "inform_user", "record_resolution",
    }
    missing = expected - nodes
    assert not missing, f"missing nodes: {missing}"


def test_ensemble_retriever_builds_bm25_only():
    """build_ensemble() must tolerate a missing vector store (BM25-only)."""
    from rag.retriever import EnsembleRetriever
    from langchain_core.documents import Document

    retriever = EnsembleRetriever(use_reranker=False)
    built = retriever.build_ensemble(
        vectorstore=None,
        corpus_docs=[
            Document(
                page_content="Password reset via the self-service portal",
                metadata={"source": "kb.txt"},
            )
        ],
    )
    assert built is not None
    assert retriever._retriever is not None
    docs = retriever.retrieve("how do I reset a password")
    assert len(docs) >= 1


def test_ensemble_retriever_requires_some_retriever():
    """build_ensemble() must fail loudly when no vector store AND no corpus."""
    from rag.retriever import EnsembleRetriever
    from core.exceptions import RAGError

    retriever = EnsembleRetriever(use_reranker=False)
    with pytest.raises(RAGError):
        retriever.build_ensemble(vectorstore=None, corpus_docs=[])


def test_pipeline_degrades_when_no_retrievers(monkeypatch):
    """Pipeline must return a helpful no-info answer, not raise, when empty."""
    from rag.pipeline import RAGPipeline
    from core.exceptions import RAGError

    # Isolate: no BM25 corpus (memory empty) and no vector store.
    monkeypatch.setattr(RAGPipeline, "_load_memory_docs", lambda self, tenant_id=1: [])
    monkeypatch.setattr(
        RAGPipeline,
        "_get_retriever",
        lambda self, tenant_id: (_ for _ in ()).throw(
            RAGError("no retrievers available")
        ),
    )

    pipe = RAGPipeline()
    result = pipe.run(
        question="how do I reset a password",
        use_memory=False,
    )
    assert result.retrieved_chunks == 0
    assert "couldn't find" in result.answer.lower() or "information" in result.answer.lower()