<div align="center">

# 🤖 HelpDesk Enterprise Copilot v12

**Agente RAG de soporte IT empresarial con memoria autocapacitada**
Aprende de cada caso resuelto y mejora con el uso. Funciona con **Google Gemini gratis** (LLM + embeddings) y se despliega en la nube pública **sin costo**.

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.96C341?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agents-1C3C3C?logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Gemini](https://img.shields.io/badge/Gemini-Free-4285F4?logo=google&logoColor=white)](https://aistudio.google.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](./Dockerfile)
[![Tests](https://img.shields.io/badge/Tests-34%20passed-2ea44f)](#-ejecutar-los-tests)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/dfserver1/helpdesk-agentico/pulls)

**Código abierto y gratuito (MIT).** Úsalo, modifícalo y contribuye.

</div>

---

## ✨ Demo

> 🎬 *Pendiente: agrega tu grabación (`.gif`) en `docs/demo.gif` y enlázala aquí.*

| Cliente | Agente |
|---------|--------|
| `<tu video o gif de demostración>` | `<tu video o gif de respuesta>` |

---

## 🧠 Qué hace

Un **HelpDesk con IA** que responde dudas de TI, clasifica incidentes con
prioridad ITSM (P1–P4), cumple SLAs, abre tickets con aprobación humana y
**aprende** de cada caso resuelto para mejorar sus respuestas futuras.

- 🔍 **RAG híbrido** — BM25 + embeddings vectoriales + reranking CrossEncoder
- 🧠 **Memoria autocapacitada** — casos resueltos y feedback se reutilizan
- 🧵 **Concurrencia** — sesiones paralelas + sub-agentes (map-reduce)
- 🔌 **Conectores** — SharePoint / Teams / Outlook (Microsoft Graph) + web search
- 🎯 **SLA/ITSM** — clasificación P1–P4, escalado y human-in-the-loop
- 🔐 **Auth completa** — JWT + RBAC + SSO (Google / Microsoft 365)
- 🖥️ **UI + API + CLI** — Streamlit, FastAPI con Swagger, y terminal

---

## 🏗️ Arquitectura

```text
                ┌──────────────────────────────────────────────────────┐
                │                      CLIENTES                         │
                │   Streamlit UI │ REST API │ CLI │ Copilot Studio      │
                └───────────────┬──────────────────────────────────────┘
                                │ HTTP (JWT / OAuth)
                ┌───────────────▼──────────────────────────────────────┐
                │                    FASTAPI (api/)                     │
                │      Auth │ RBAC │ Rate limit │ Chat │ Tickets        │
                └───────────────┬──────────────────────────────────────┘
                                │
                ┌───────────────▼──────────────────────────────────────┐
                │           AGENTE LangGraph (agent/)                  │
                │   Planifica → Recupera → Genera → Memoria → Ticket   │
                │   (concurrencia + sub-agentes en app/concurrency.py) │
                └───────┬──────────────┬───────────────┬───────────────┘
                        │              │               │
         ┌──────────────▼───┐  ┌───────▼────────┐  ┌───▼──────────────┐
         │  RAG (rag/)      │  │ Conectores     │  │ LLM Providers    │
         │  BM25 + vectores │  │ Graph O365     │  │ Gemini (gratis)  │
         │  + reranking     │  │ + Web Search   │  │ / Azure OpenAI   │
         └───────┬──────────┘  └───────┬────────┘  └───────┬──────────┘
                 │                     │                    │
         ┌───────▼──────────┐  ┌───────▼────────┐  ┌───────▼──────────┐
         │   STORAGE        │  │  CHROMA DB     │  │  GEMINI API      │
         │  Supabase/Postgres│ │ (vector store) │  │  (embeddings)    │
         │  o SQLite local  │  └────────────────┘  └──────────────────┘
         └──────────────────┘
```

---

## ✅ Lo que incluye

| Módulo | Descripción |
|--------|-------------|
| [`agent/`](./agent) | Grafo LangGraph: RAG correctivo, clasificación ITSM, SLA, aprobación humana |
| [`rag/`](./rag) | Recuperación híbrida BM25 + vectores + reranking CrossEncoder |
| [`connectors/`](./connectors) | Microsoft Graph (SharePoint/Teams/Outlook) + búsqueda web |
| [`services/`](./services) | Memoria autocapacitada: episódica, case-studies, feedback |
| [`api/`](./api) | FastAPI: JWT + RBAC, tickets, chat, ingest, estadísticas, rate limit |
| [`app/concurrency.py`](./app/concurrency.py) | Sesiones paralelas + sub-agentes map-reduce |
| [`auth/`](./auth) | OAuth Google y Microsoft 365 (Authorization Code + PKCE) |
| [`ui/`](./ui) | Interfaz Streamlit: login, chat, tickets, memoria, admin |
| [`sla/`](./sla) | Clasificador P1–P4 y cálculo de SLA |
| [`scripts/`](./scripts) | Bootstrap, seed de admin, arranque API/UI/CLI |
| [`tests/`](./tests) | 34 tests de funcionalidad y seguridad + evaluación RAG |

---

## 🚀 Inicio rápido (modo gratis con Gemini)

### Requisitos

| Herramienta | Para qué |
|-------------|----------|
| **Python 3.10+** (probado 3.13) | Ejecutar el código |
| **Google AI Studio** (gratis) | API key de Gemini + embeddings |
| Docker *(opcional)* | Despliegue contenedorizado |

### 1. Clona e instala

```bash
git clone https://github.com/dfserver1/helpdesk-agentico.git
cd helpdesk-agentico
python scripts/bootstrap.py    # crea .venv, instala deps y genera .env
```

Equivalente manual:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Crea tu API key gratis de Gemini

1. Entra en **https://aistudio.google.com/apikey**
2. Clic en **Create API key** (empieza con `AIza...`).
3. Un proyecto nuevo puede tardar unos minutos en activarse la clave.

### 3. Configura `.env` (solo lo mínimo)

```dotenv
LLM_PROVIDER=google_gemini
GOOGLE_API_KEY=AIza...tu_clave_aqui
GEMINI_MODEL=gemini-3.5-flash
JWT_SECRET_KEY=            # local: vacío OK; producción: 32+ caracteres
DATABASE_URL=sqlite+aiosqlite:///./helpdesk.db
ADMIN_EMAIL=admin@helpdesk.ai
ADMIN_PASSWORD=muy_fuerte_y_unica
DEBUG=true
ENVIRONMENT=development
```

### 4. Arranca

```bash
python scripts/seed.py          # crea el admin (idempotente)
python scripts/run_api.py       # API  → http://localhost:8000  (/docs = Swagger)
python scripts/run_ui.py        # UI   → http://localhost:8501
python scripts/run_cli.py       # CLI  → interactivo en terminal
```

### 5. Ejecuta los tests

```bash
python -m pytest
```

---

## ☁️ Despliegue GRATIS en producción

| Guía | Descripción |
|------|-------------|
| 📘 [**Guía paso a paso**](./docs/GUIA_PASO_A_PASO.md) | Para no técnicos (imprimible: `docs/GUIA_PASO_A_PASO.html`) |
| 📄 [**docs/DEPLOY_GOOGLE.md**](./docs/DEPLOY_GOOGLE.md) | HF Spaces (Docker) + Supabase + Gemini |
| 🤖 [**docs/DEPLOY_COPILOT_STUDIO.md**](./docs/DEPLOY_COPILOT_STUDIO.md) | Conectar a Microsoft Copilot Studio (`docs/copilot_studio_openapi.json`) |

También puedes correrlo en tu propio Docker:

```bash
export JWT_SECRET_KEY=...
export ADMIN_EMAIL=...
export ADMIN_PASSWORD=...
export LLM_PROVIDER=google_gemini
export GOOGLE_API_KEY=...
docker compose up --build
# API: http://localhost:8000   |  UI: http://localhost:8501
```

---

## 🔌 API (principales endpoints)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Registro (rol `user`) |
| POST | `/api/v1/auth/login` | Login → par de tokens (10/min) |
| POST | `/api/v1/auth/refresh` | Renovar token |
| GET | `/api/v1/auth/me` | Usuario actual |
| GET | `/api/v1/auth/oauth/{p}/login` | Iniciar login SSO (google/microsoft) |
| GET | `/api/v1/auth/oauth/{p}/callback` | Callback SSO |
| POST | `/api/v1/chat` | Preguntar al agente (multihilo) |
| POST | `/api/v1/chat/{id}/decide` | Aprobar/rechazar borrador de ticket |
| GET/POST | `/api/v1/tickets` | Listar / crear ticket (calcula SLA) |
| GET | `/api/v1/tickets/{id}` | Detalle de ticket |
| GET | `/api/v1/connectors/status` | Estado de conectores O365 + web |
| POST | `/api/v1/connectors/search` | Buscar SharePoint/Teams/Outlook/web |
| POST | `/api/v1/memory/ingest` | Enseñar al agente (self-training) |
| POST | `/api/v1/memory/recall` | Recuperar memoria aprendida |
| POST | `/api/v1/memory/case-studies` | Añadir case-study |
| GET | `/api/v1/admin/stats` | Estadísticas (solo admin) |
| GET | `/api/v1/health` | Health check |

### Ejemplo de chat

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@helpdesk.ai","password":"tu_password"}' | jq -r .access_token)

curl -s -X POST localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Outlook crashes on startup"}'
```

La respuesta incluye `used_connectors`, `used_web_search` y `subagent_results`
para auditar el origen de la respuesta (KB, conectores o web).

---

## 🧠 Self-training (memoria que aprende)

1. Ingiere un caso resuelto:

   ```json
   { "payload": { "issue": "VPN no conecta en casa",
                  "resolution": "Registrar en AAD y resetear credenciales",
                  "priority": "P2" } }
   ```

2. La memoria episódica se persiste en Supabase/Postgres.
3. En futuras consultas, `recall()` y el BM25 reutilizan esa solución aprendida
   y el pipeline la fusiona con los resultados vectoriales.
4. Admins/agentes pueden añadir **case-studies** etiquetados.

---

## 🛠️ Solución de problemas

| Síntoma | Causa / solución |
|---------|------------------|
| `ConfigurationError: GOOGLE_API_KEY` | La key falta o es placeholder; rellena `.env`/secret. |
| `ValueError: JWT_SECRET_KEY ...` | En prod debe tener 32+ caracteres. |
| `Rate limit exceeded (429)` | Login 10/min, chat 60/min; sube `RATE_LIMIT_PER_MINUTE`. |
| Chat dice "no encontré información" | Sin docs indexados ni memoria; usa `connectors/search`. |
| `DataError` fechas en Supabase | Usar `DATABASE_URL` con `?ssl=require` y Postgres. |
| Space HF "App not running" | Dockerfile arranca en `$PORT`; revisa los secrets. |
| Connectores devuelven vacío | `CONNECTORS_ENABLED=true` + `GRAPH_*` válidos; revisa `GET /connectors/status`. |
| OAuth "provider not configured" | Faltan `GOOGLE_OAUTH_*` / `MICROSOFT_OAUTH_*` en `.env`. |
| `ModuleNotFoundError` al instalar | `pip install -r requirements.txt` en el venv. |

---

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Por favor:

1. **Fork** el repositorio.
2. Crea tu rama de feature (`git checkout -b feat/mi-mejora`).
3. Haz **commit** de tus cambios.
4. Haz **push** y abre un **Pull Request**.

---

## 📄 Licencia

**MIT License** — Copyright (c) 2026 **Omar Pajares**.

Proyecto de código abierto y gratuito: puedes usarlo, modificarlo y
redistribuirlo libremente, incluso en empresas, con la única condición de
conservar el aviso de copyright. Ver [LICENSE](./LICENSE).

<div align="center">
  <sub>Hecho con ❤️ por la comunidad · HelpDesk Enterprise Copilot v12</sub>
</div>
