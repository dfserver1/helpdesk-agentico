"""
Concurrency infrastructure for HelpDesk Enterprise Copilot v12.

Provides:
  - A shared ThreadPoolExecutor for running blocking/CPU-heavy work (LLM,
    retrieval, embeddings, Chroma) off the asyncio event loop so that many
    user sessions can run in parallel without stalling one another.
  - A global semaphore that caps how many agent runs execute at once,
    guaranteeing the runtime never saturates under burst load.
  - ``run_subtasks`` to fan out heavy tasks into parallel sub-agent workers
    (map-reduce style) with a bounded worker count.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Coroutine, List, Optional

from config.logging import get_logger
from config.settings import get_settings

logger = get_logger("concurrency")

_executor: Optional[ThreadPoolExecutor] = None
_agent_semaphore: Optional[asyncio.Semaphore] = None


def get_executor() -> ThreadPoolExecutor:
    """Return the shared thread pool (lazily created with settings)."""
    global _executor
    if _executor is None:
        settings = get_settings()
        _executor = ThreadPoolExecutor(
            max_workers=settings.CHAT_EXECUTOR_THREADS,
            thread_name_prefix="agent-worker",
        )
        logger.debug(
            f"ThreadPool started (workers={settings.CHAT_EXECUTOR_THREADS})"
        )
    return _executor


def get_agent_semaphore() -> asyncio.Semaphore:
    """Global semaphore limiting concurrent agent runs."""
    global _agent_semaphore
    if _agent_semaphore is None:
        settings = get_settings()
        _agent_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_SESSIONS)
    return _agent_semaphore


async def run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """
    Run a synchronous, potentially blocking function in a worker thread.

    Use when calling from async code (FastAPI route / async LangGraph node) so
    the event loop stays responsive for other sessions.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_executor(), lambda: fn(*args, **kwargs)
    )


async def run_agent_blocking(
    invoke_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Execute ``invoke_fn(*args)`` under the global concurrency cap.

    ``invoke_fn`` should be the *synchronous* invocation of a LangGraph agent
    (``agent.invoke``), which internally does blocking LLM/retrieval work.
    The function runs in a worker thread; the semaphore guarantees no more
    than ``MAX_CONCURRENT_SESSIONS`` heavy agent runs at the same time.
    """
    settings = get_settings()
    semaphore = get_agent_semaphore()
    logger.debug(
        f"Agent run queued: active={semaphore.locked()} "
        f"limit={settings.MAX_CONCURRENT_SESSIONS}"
    )
    async with semaphore:
        return await run_in_thread(invoke_fn, *args, **kwargs)


async def run_agent_async_blocking(
    agent: Any,
    state: Any,
    config: Optional[dict] = None,
) -> Any:
    """
    Run an async LangGraph agent (``agent.ainvoke``) inside a worker thread.

    The coroutine ``agent.ainvoke(state, config=config)`` is wrapped with
    ``asyncio.run()`` inside the worker thread, giving each session its own
    event loop and true parallelism for blocking LLM/retrieval work, all under
    the shared semaphore that caps total concurrent agent runs.
    """
    config = config or {}
    semaphore = get_agent_semaphore()
    logger.debug(f"Agent (async) queued under semaphore (cap {get_settings().MAX_CONCURRENT_SESSIONS})")
    async with semaphore:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            get_executor(),
            lambda: asyncio.run(agent.ainvoke(state, config=config)),
        )


async def run_subtasks(
    subtasks: List[Coroutine[Any, Any, Any]] | List[Awaitable[Any]],
    max_workers: Optional[int] = None,
) -> List[Any]:
    """
    Run a list of awaitables concurrently (map phase), bounded by a semaphore
    sized ``max_workers`` (defaults to ``SUBTASK_MAX_WORKERS``). Returns a list
    of results in the same order as the input. Exceptions are caught and
    returned per-item so one failing subtask never aborts the whole batch.
    """
    settings = get_settings()
    workers = max_workers or settings.SUBTASK_MAX_WORKERS
    sem = asyncio.Semaphore(workers)

    async def _guarded(coro: Awaitable[Any]) -> Any:
        async with sem:
            return await coro

    results = await asyncio.gather(
        *(_guarded(c) for c in subtasks),
        return_exceptions=True,
    )
    return list(results)


async def run_subtasks_threads(
    funcs: List[Callable[[], Any]],
    max_workers: Optional[int] = None,
) -> List[Any]:
    """Map-phase over a list of synchronous callables using the thread pool."""
    return await run_subtasks(
        [run_in_thread(fn) for fn in funcs],
        max_workers=max_workers,
    )


def submit_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any):
    """Fire-and-forget background thread task (e.g. async self-training)."""
    return get_executor().submit(fn, *args, **kwargs)