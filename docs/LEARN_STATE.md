# 🧠 Registro de Aprendizaje e Implementación Continua (Learn State)
**Fecha:** 2026-08-15  
**Proyecto:** HelpDesk Enterprise  
**Ruta del Repositorio:** `HelpDesk Enterprise Copilot v12 Repository/helpdesk_copilot`  
**Skills Integradas:** `security-audit`, `top-web-vulnerabilities`, `python-fastapi-development`, `langgraph`, `similarity-search-patterns`.

---

## 📌 1. Arquitectura y Módulos del Sistema
- **Backend API:** FastAPI con endpoints de Auth (JWT, RBAC, OAuth PKCE para Google y Microsoft), Chat RAG, Tickets ITSM, Conectores y Memoria.
- **RAG Híbrido & Agente:** LangGraph con SQLite checkpointer, búsqueda densa (ChromaDB) + léxica (BM25), reordenamiento con CrossEncoder y mitigación de prompt injection (`utils/prompt_security.py`).
- **Motor ITSM / SLAs:** Clasificación P1–P4, tiempos de resolución hábiles y soporte multi-backend (Database, Freshservice, Jira).
- **Frontend & CLI:** Streamlit (`ui/app.py`) con soporte completo de chats, aprobación de tickets (Human-in-the-loop) y autoentrenamiento; CLI interactiva en `scripts/run_cli.py`.
- **Contenerización:** Dockerfile y `docker-compose.yml` listos para PostgreSQL, API y Streamlit.

---

## 🔌 2. Conectores Empresariales Implementados
1. **Microsoft 365 (Microsoft Graph Client):**
   - **SharePoint:** Búsqueda en sitios y librerías de documentos (`connectors/o365.py`).
   - **Teams:** Búsqueda en canales y mensajes de chat.
   - **Outlook:** Búsqueda en correos y carpetas de soporte.
2. **Google Workspace (Google Client):**
   - **Google Drive & Docs:** Extracción de documentos corporativos, manuales y archivos (`connectors/google.py`, `connectors/google_client.py`).
   - **Gmail:** Búsqueda de hilos de soporte, alertas y correos de resolución.
   - **Autenticación:** Soporte de Google Service Account (Domain-Wide Delegation) y tokens OAuth2.
3. **Web Search Fallback:**
   - DuckDuckGo + Wikipedia + soporte opcional para Tavily / Brave Search (`connectors/web_search.py`).

---

## 🧠 3. Mecanismo de Autoentrenamiento Empresarial (Harvest & Auto-Learn)
- **Endpoint API:** `POST /api/v1/memory/sync-connectors`
- **Frontend:** Pestaña `⚡ Enterprise Sync & Auto-Train` en `ui/app.py`.
- **Funcionamiento:** Extrae en paralelo guías y correos de resolución desde Google Drive, Gmail, SharePoint, Teams y Outlook, almacenándolos en la base de datos de memoria episódica/semántica (`MemoryService`). El agente los utiliza automáticamente en el RAG para responder futuras dudas de forma autónoma.

---

## 🛡️ 4. Blindaje de Seguridad y Calidad Aplicado
- **Seguridad (OWASP Top 10 & LLM Top 10):**
  - Validación estricta contra OAuth Open Redirects (`api/routes/oauth.py`).
  - Protección contra IDOR en tickets (`api/routes/tickets.py`).
  - Módulo de sanitización de prompts, inyecciones indirectas y fuga de datos en Markdown (`utils/prompt_security.py`).
  - Protección SSRF y bloqueo de IPs de metadatos cloud (`connectors/web_search.py`).
  - Cabeceras de seguridad HTTP (`nosniff`, `DENY`, HSTS).
- **Calidad y Estabilidad:**
  - Semáforos asíncronos *loop-aware* y cierre limpio de hilos en `app/concurrency.py`.
  - Sesiones HTTP per-request en `ui/api_client.py` para prevenir cierres de bucle en Streamlit.
  - Sincronización thread-safe en ChromaDB y protección contra listas vacías en BM25.

---

## 💬 5. Persistencia Multisesión y Recuperación de Conversaciones
- **Endpoints de Historial ([`api/routes/chat.py`](file:///C:/Users/Omar/OneDrive%20-%20MSFT/Plataforma/Agente%20HelpDesk/HelpDesk%20Enterprise%20Copilot%20v12%20Repository/helpdesk_copilot/api/routes/chat.py)):**
  - Almacenamiento automático en base de datos (`Message` y `ChatSession`).
  - `GET /api/v1/chat/sessions`: Listado de conversaciones por usuario.
  - `GET /api/v1/chat/sessions/{session_id}/messages`: Recuperación del historial completo al reconectar.
- **Frontend Streamlit ([`ui/app.py`](file:///C:/Users/Omar/OneDrive%20-%20MSFT/Plataforma/Agente%20HelpDesk/HelpDesk%20Enterprise%20Copilot%20v12%20Repository/helpdesk_copilot/ui/app.py)):** Barra lateral interactiva para crear y cambiar entre conversaciones anteriores sin perder el contexto.
- **Identidad Gráfica:** Logotipo corporativo de IA y soporte generado e integrado en `ui/logo.png`.

---

## 🚀 6. Instrucciones Rápidas para Retomar
Para reanudar o levantar el proyecto:
```bash
# 1. Levantar con Docker:
docker compose up --build -d

# 2. O levantar localmente:
uvicorn app.main:app --reload --port 8000
streamlit run ui/app.py
```
