"""
Core RAG pipeline for HelpDesk Enterprise Copilot v12.

Full flow:
  1. Rewrite query for better retrieval (using chat history)
  2. Ensemble retrieval (BM25 + Vector) + CrossEncoder reranking
  3. Build context from top-k chunks
  4. Generate grounded answer via LLM
  5. Parse answer, confidence score, suggested follow-ups
  6. Return structured RAGResult with citations

Self-training hooks: every query/result can be recorded into memory for
continuous improvement (Phase 4).
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import get_settings
from config.logging import get_logger
from rag.llm import get_chat_llm
from rag.retriever import EnsembleRetriever
from vector_db.chroma_store import get_vector_store
from core.exceptions import RAGError

logger = get_logger("rag_pipeline")


# --- Data classes ---------------------------------------------------------

@dataclass
class SourceCitation:
    document_name: str
    page_number: Optional[int]
    chunk_text: str
    relevance_score: float
    source_type: str = "knowledge_base"


@dataclass
class RAGResult:
    answer: str
    sources: List[SourceCitation]
    confidence_score: float
    suggested_questions: List[str]
    response_time_ms: float
    query_used: str
    retrieved_chunks: int = 0
    used_self_trained_memory: bool = False
    priority: Optional[str] = None
    category: Optional[str] = None
    sla_response_time: Optional[str] = None


# --- Prompt templates ------------------------------------------------------

QUERY_REWRITE_TEMPLATE = """You are a query optimization assistant for an IT helpdesk.
Rewrite the user's question to be more specific and retrieval-friendly for a document
search system. Focus on technical keywords (error codes, product names, symptoms).

Chat history (last 3 exchanges):
{chat_history}

Original question: {question}

Rewrite the question to be standalone, specific, and optimized for semantic search.
Return ONLY the rewritten question, nothing else.
"""

RAG_ANSWER_TEMPLATE = """You are {company}, an expert enterprise IT support assistant.
Answer the user's question using ONLY the information provided in the context below.

CRITICAL RULES:
- Base your answer strictly on the provided context
- If the context doesn't contain enough information, say so clearly and suggest next steps
- Never make up information not present in the context
- Cite the source document and page when referencing specific information
- Be concise but comprehensive. Use markdown if helpful.
- Respond in the language: {language}

=== CONTEXT ===
{context}

=== CHAT HISTORY ===
{chat_history}

=== USER QUESTION ===
{question}

=== YOUR ANSWER ===
Provide a helpful, accurate answer based strictly on the context above.

After your answer, on a new line, output exactly:
CONFIDENCE: [number between 0.0 and 1.0]
SUGGESTED_QUESTIONS:
- [follow-up question 1]
- [follow-up question 2]
- [follow-up question 3]
"""


# --- Query rewriting --------------------------------------------------------

def rewrite_query(question: str, chat_history: str = "", llm=None) -> str:
    """Rewrite the user question for better retrieval. Falls back to original."""
    if not chat_history.strip():
        return question

    try:
        llm = llm or get_chat_llm(temperature=0)
        prompt = QUERY_REWRITE_TEMPLATE.format(
            chat_history=chat_history,
            question=question,
        )
        response = llm.invoke(prompt)
        rewritten = response.content.strip()
        logger.debug(f"Query rewritten: '{question}' -> '{rewritten}'")
        return rewritten
    except Exception as e:
        logger.warning(f"Query rewrite failed, using original: {e}")
        return question


# --- Context builder ------------------------------------------------------
def build_context(docs: list) -> str:
    """Format retrieved documents into a numbered context block.

    Accepts LangChain ``Document`` objects OR plain dicts with keys
    ``document_name``/``chunk_text``/``relevance_score`` (as produced by the
    LangGraph retrieve node).
    """
    parts = []
    for i, doc in enumerate(docs, 1):
        if isinstance(doc, dict):
            source = doc.get("document_name", "Unknown")
            page = doc.get("page_number", "N/A")
            score = doc.get("relevance_score", 0.0)
            content = doc.get("chunk_text", "")
        else:
            source = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", "N/A")
            score = doc.metadata.get("relevance_score", 0.0)
            content = doc.page_content
        parts.append(
            f"[Source {i}: {source} | Page: {page} | Relevance: {score:.2f}]\n{content}"
        )
    return "\n\n---\n\n".join(parts)


# --- Response parser -------------------------------------------------------
def parse_llm_response(raw_response: str) -> tuple:
    """Parse LLM output into (answer, confidence, suggested_questions)."""
    answer = raw_response
    confidence = 0.7
    suggested = []

    try:
        if "CONFIDENCE:" in raw_response:
            parts = raw_response.split("CONFIDENCE:")
            answer = parts[0].strip()
            remainder = parts[1].strip()

            conf_line = remainder.split("\n")[0].strip()
            try:
                confidence = float(conf_line)
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                pass

            if "SUGGESTED_QUESTIONS:" in remainder:
                sq_part = remainder.split("SUGGESTED_QUESTIONS:")[1]
                for line in sq_part.strip().split("\n"):
                    line = line.strip().lstrip("-").strip()
                    if line:
                        suggested.append(line)
    except Exception as e:
        logger.warning(f"Response parsing error: {e}")

    return answer, confidence, suggested[:3]


# --- Main pipeline ---------------------------------------------------------

class RAGPipeline:
    """Executes the full RAG retrieval-augmented generation flow."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._retrievers: dict[int, EnsembleRetriever] = {}

    def _get_retriever(self, tenant_id: int) -> EnsembleRetriever:
        """Build a lazily-cached, tenant-scoped ensemble retriever."""
        if tenant_id not in self._retrievers:
            self._retrievers[tenant_id] = self._build_retriever(tenant_id)
        return self._retrievers[tenant_id]

    def _build_retriever(self, tenant_id: int) -> EnsembleRetriever:
        """Construct the ensemble retriever for a single tenant."""
        from rag.retriever import EnsembleRetriever

        corpus_docs = self._load_memory_docs(tenant_id=tenant_id)
        vectorstore = None
        try:
            from vector_db.chroma_store import get_vector_store

            vectorstore = get_vector_store()
        except Exception as e:
            # Vector store unavailable (e.g. embeddings not configured yet).
            # Degrade to BM25-only retrieval over the memory corpus so the
            # pipeline still works in partially-configured deployments.
            logger.warning(
                f"Vector store unavailable, falling back to BM25-only "
                f"retrieval: {e}"
            )
        retriever = EnsembleRetriever(
            k_initial=self.settings.TOP_K_RESULTS,
            k_final=self.settings.RERANK_TOP_K,
        )
        retriever.build_ensemble(
            vectorstore,
            corpus_docs=corpus_docs,
            tenant_id=tenant_id,
        )
        return retriever

    def _load_memory_docs(self, tenant_id: int = 1) -> list:
        """Load self-trained memory / case studies into BM25 corpus (Phase 4 hook)."""
        try:
            from services.memory_service import MemoryService
            service = MemoryService()
            docs = service.get_retrieval_documents_sync(tenant_id=tenant_id)
            if docs:
                logger.debug(f"Loaded {len(docs)} memory documents into BM25 corpus")
            return docs
        except Exception as e:
            logger.debug(f"No memory docs loaded for BM25: {e}")
            return []

    def _maybe_memory(self, question: str, tenant_id: int):
        """Return (used, context) if a high-confidence self-trained memory exists."""
        try:
            from services.memory_service import MemoryService
            service = MemoryService()
            return service.get_relevant_context_sync(tenant_id, question)
        except Exception as e:
            logger.debug(f"Memory lookup skipped: {e}")
            return False, None

    def run(
        self,
        question: str,
        chat_history: List[dict] = None,
        language: str = "en",
        tenant_id: int = 1,
        document_filter: dict = None,
        use_memory: bool = True,
    ) -> RAGResult:
        """Execute the end-to-end RAG query."""
        start_time = time.time()
        chat_history = chat_history or []

        history_str = "\n".join(
            f"{m.get('role', '').upper()}: {m.get('content', '')}"
            for m in chat_history[-6:]
        )

        # Step 1: Query rewriting
        rewritten_query = rewrite_query(question, history_str)
        logger.debug(f"RAG query: '{rewritten_query}'")

        # Step 2: Retrieval
        try:
            retriever = self._get_retriever(tenant_id)
            docs = retriever.retrieve(rewritten_query)
        except RAGError as e:
            # No retrievers available (empty corpus / not yet indexed, or
            # embeddings unavailable). Degrade to a helpful "no info" response
            # rather than failing the request.
            logger.warning(f"Retrieval degraded, no sources available: {e}")
            docs = []
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            raise RAGError(f"RAG retrieval failed: {e}")

        retrieved_count = len(docs)

        # Step 2b: Memory enhancement (Phase 4 hook)
        memory_used, memory_context = False, None
        if use_memory:
            memory_used, memory_context = self._maybe_memory(question, tenant_id)

        # Step 3: Build context
        context = build_context(docs)

        include_memory_context = memory_used and memory_context

        if include_memory_context:
            context = f"[REMEMBERED FROM PAST CASES]\n{memory_context}\n\n---\n\n{context}"

        if not docs and not include_memory_context:
            elapsed = (time.time() - start_time) * 1000
            return RAGResult(
                answer=(
                    "I couldn't find relevant information in the knowledge base to answer your question. "
                    "Please ensure relevant documents are indexed, or rephrase your question."
                ),
                sources=[],
                confidence_score=0.0,
                suggested_questions=[
                    "What topics are covered in the knowledge base?",
                    "Can you upload more documentation?",
                    "Could you rephrase your question?",
                ],
                response_time_ms=elapsed,
                query_used=rewritten_query,
                retrieved_chunks=0,
                used_self_trained_memory=False,
            )

        # Step 4: Generate answer
        llm = get_chat_llm(temperature=0.15)
        prompt = RAG_ANSWER_TEMPLATE.format(
            company=self.settings.APP_NAME,
            context=context,
            question=question,
            chat_history=history_str,
            language=language,
        )

        try:
            response = llm.invoke(prompt)
            raw_answer = response.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            raise RAGError(f"RAG generation failed: {e}")

        # Step 5: Parse response
        answer, confidence, suggested_questions = parse_llm_response(raw_answer)

        # Step 6: Citations
        sources: List[SourceCitation] = []
        for doc in docs:
            sources.append(
                SourceCitation(
                    document_name=doc.metadata.get("source", "Unknown"),
                    page_number=doc.metadata.get("page"),
                    chunk_text=(
                        doc.page_content[:300] + "..."
                        if len(doc.page_content) > 300
                        else doc.page_content
                    ),
                    relevance_score=doc.metadata.get("relevance_score", 0.0),
                )
            )

        elapsed = (time.time() - start_time) * 1000
        logger.info(
            f"RAG completed in {elapsed:.0f}ms | confidence={confidence:.2f} | "
            f"chunks={retrieved_count} | memory={memory_used}"
        )

        return RAGResult(
            answer=answer,
            sources=sources,
            confidence_score=confidence,
            suggested_questions=suggested_questions,
            response_time_ms=elapsed,
            query_used=rewritten_query,
            retrieved_chunks=retrieved_count,
            used_self_trained_memory=memory_used,
        )


# --- Facade ---------------------------------------------------------------
_pipeline = None


def get_rag_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RAGPipeline()
    return _pipeline