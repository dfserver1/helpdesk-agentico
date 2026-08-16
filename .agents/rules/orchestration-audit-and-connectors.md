---
name: orchestration-audit-and-connectors
description: Enforces multi-agent auditing (Security + Quality) and enterprise connector standards for HelpDesk Copilot.
always_apply: true
---

# HelpDesk Copilot Orchestration & Engineering Standards

## 1. Multi-Agent Audit Protocol
Whenever auditing, debugging, or reviewing code changes:
- Deploy a dedicated **Security Auditor Subagent** to check and remediate:
  - OWASP Top 10 / LLM Top 10 (prompt injection sanitization via `utils/prompt_security.py`).
  - IDOR on ticket endpoints and safe OAuth redirect URL validation.
  - SSRF protection on external connectors and web search.
- Deploy a dedicated **Quality & Concurrency Subagent** to check and remediate:
  - Async/sync event loop safety (avoiding raw `asyncio.run()` in active loops).
  - Runtime exception handling, SLA calculations, and database connection leaks.

## 2. Enterprise Connector & Memory Ingestion Architecture
- Support dual enterprise ecosystems: Microsoft 365 (Graph API) and Google Workspace (Drive & Gmail).
- Ensure connectors are pluggable via `connectors/registry.py` and feed into the self-training memory service (`POST /api/v1/memory/sync-connectors`).

## 3. Session State Persistence
- Maintain architectural decisions and state in `docs/LEARN_STATE.md` for seamless context resumption across sessions.
