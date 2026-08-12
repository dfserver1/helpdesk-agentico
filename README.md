# HelpDesk Enterprise Copilot v12

Agente RAG de soporte IT empresarial con **memoria autocapacitada**: aprende de
cada caso resuelto y mejora con el uso. Ejecuta con **Google Gemini gratis**
(LLM + embeddings) y se puede desplegar en la nube pública **sin costo**:
**Hugging Face Spaces** (backend) + **Supabase** (base de datos) + **GitHub**
(código abierto), y se conecta a **Microsoft Copilot Studio** como agente.

---

## 1. Qué incluye

- **Agente LangGraph** (`agent/`) — RAG correctivo: recuperación híbrida
  (BM25 + vectores + reranking CrossEncoder), clasificación ITSM P1–P4,
  cumplimiento de SLA y aprobación humana de tickets (human-in-the-loop).
- **Ejecución multihilo y sub-agentes** (`app/concurrency.py`) — varias sesiones
  en paralelo bajo un semáforo global, y tareas pesadas descompuestas en
  sub-agentes en paralelo (map-reduce).
- **Conectores externos** (`connectors/`) — Microsoft Graph (SharePoint / Teams /
  Outlook) y **búsqueda web** como fallback cuando no hay documentación interna.
- **Memoria autocapacitada** (`services/memory_service.py`) — casos resueltos,
  case-studies y feedback se guardan como memoria episódica y se recuperan en
  respuestas futuras.
- **API REST** (`api/`) — FastAPI: JWT + RBAC (user / agent / manager / admin),
  tickets, chat, ingest de memoria, estadísticas. Con rate limiting.
- **Login SSO** — OAuth con **Google** y **Microsoft 365** (Authorization Code +
  PKCE), vinculado a la cuenta local por email o `oauth_subject`.
- **UI Streamlit** (`ui/`) — login (email o SSO), chat, tickets, memoria, admin.
- **CLI interactivo** — `python scripts/run_cli.py` para probar el agente
  desde la terminal (conectado a la API o `--local` sin servidor).
- **Suite de pruebas** — 34 tests de funcionalidad/seguridad + evaluación RAG.

---

## 2. Requisitos previos

| Herramienta                    | Para qué                                           |
|--------------------------------|----------------------------------------------------|
| Python 3.10+ (probado 3.13)    | Ejecutar el código                                 |
| Git                            | Publicar en GitHub                                 |
| Cuenta GitHub                  | Repositorio público (código abierto)               |
| **Google AI Studio** (gratis)  | API key para Gemini + embeddings                   |
| Cuenta **Hugging Face** (gratis)| Space Docker público                                |
| Cuenta **Supabase** (gratis)   | PostgreSQL 500 MB para datos                       |
| Microsoft Copilot Studio       | (Opcional) conectar el agente                      |

> **Modo gratis recomendado: Gemini.** `LLM_PROVIDER=google_gemini` usa
> `gemini-3.5-flash` + `models/gemini-embedding-001` sin pagar nada. Azure OpenAI
> es opcional (de pago).

---

## 3. Instalación y configuración local (paso a paso)

### 3.1 Clonar / abrir el proyecto

```bash
git clone https://github.com/dfserver1/helpdesk-agentico.git
cd helpdesk-agentico
```

### 3.2 Crear entorno e instalar dependencias

```bash
python scripts/bootstrap.py
```

Equivalente manual:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
```

`bootstrap.py` también crea `.env` a partir de `.env.example` si no existe.

### 3.3 Crear la API key gratis de Gemini

1. Entra en https://aistudio.google.com/apikey
2. Clic en **Create API key** (la clave empieza con `AIza...`).
3. Un proyecto nuevo puede tardar unos minutos en activarse la clave.

### 3.4 Configurar `.env`

Edita `.env` y rellena **solo** lo mínimo:

```dotenv
# --- Proveedor GRATIS (Gemini) ---
LLM_PROVIDER=google_gemini
GOOGLE_API_KEY=AIza...tu_clave_aqui
GEMINI_MODEL=gemini-3.5-flash

# --- Seguridad ---
# En local puedes dejarlo VACÍO (se genera efímero). En producción es
# OBLIGATORIO que tenga 32+ caracteres:
JWT_SECRET_KEY=

# --- Base de datos ---
# Local: SQLite automático
DATABASE_URL=sqlite+aiosqlite:///./helpdesk.db

# --- Admin inicial (creado por scripts/seed.py) ---
ADMIN_EMAIL=admin@helpdesk.ai
ADMIN_PASSWORD=muy_fuerte_y_unica

# --- App ---
DEBUG=true
ENVIRONMENT=development
```

### 3.5 Sembrar el super-admin y arrancar

```bash
python scripts/seed.py                 # crea el admin (idempotente)

python scripts/run_api.py              # API en http://localhost:8000
# http://localhost:8000/docs          # Swagger de la API

python scripts/run_ui.py               # UI en http://localhost:8501
python scripts/run_cli.py              # CLI interactivo (otra terminal)
```

### 3.6 Ejecutar los tests

```bash
python -m pytest
```

---

## 4. Despliegue en la nube GRATIS (producción)

Despliegue paso a paso en **Hugging Face Spaces + Supabase + Gemini** en:

- 📘 [**Guía paso a paso (para no técnicos)**](./docs/GUIA_PASO_A_PASO.md)
  (versión imprimible: `docs/GUIA_PASO_A_PASO.html`)
- 📄 [**docs/DEPLOY_GOOGLE.md**](./docs/DEPLOY_GOOGLE.md)

Conexión del agente a **Microsoft Copilot Studio** (custom connector OpenAPI):

- 📄 [**docs/DEPLOY_COPILOT_STUDIO.md**](./docs/DEPLOY_COPILOT_STUDIO.md)
- Especificación del conector: `docs/copilot_studio_openapi.json`

---

## 5. Endpoints principales (API v1)

| Método | Ruta                            | Descripción                              |
|--------|---------------------------------|------------------------------------------|
| POST   | `/api/v1/auth/register`         | Registro (rol `user`)                    |
| POST   | `/api/v1/auth/login`            | Login → par de tokens (10/min)           |
| POST   | `/api/v1/auth/refresh`          | Renovar token                            |
| GET    | `/api/v1/auth/me`               | Usuario actual                           |
| GET    | `/api/v1/auth/oauth/{p}/login`  | Iniciar login SSO (google/microsoft)     |
| GET    | `/api/v1/auth/oauth/{p}/callback` | Callback SSO (intercambia código)      |
| POST   | `/api/v1/chat`                  | Preguntar al agente (multihilo)          |
| POST   | `/api/v1/chat/{id}/decide`      | Aprobar/rechazar borrador de ticket      |
| GET/POST| `/api/v1/tickets`              | Listar / crear ticket (calcula SLA)      |
| GET    | `/api/v1/tickets/{id}`          | Detalle de ticket                        |
| GET    | `/api/v1/connectors/status`     | Estado de conectores O365 + web          |
| POST   | `/api/v1/connectors/search`     | Buscar SharePoint/Teams/Outlook/web      |
| POST   | `/api/v1/memory/ingest`         | Enseñar al agente (self-training)        |
| POST   | `/api/v1/memory/recall`         | Recuperar memoria aprendida              |
| POST   | `/api/v1/memory/case-studies`   | Añadir case-study                        |
| GET    | `/api/v1/admin/stats`           | Estadísticas (solo admin)                |
| GET    | `/api/v1/health`                | Health check                            |

Ejemplo de chat:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@helpdesk.ai","password":"tu_password"}' | jq -r .access_token)

curl -s -X POST localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Outlook crashes on startup"}'
```

La respuesta de chat incluye ahora `used_connectors`, `used_web_search` y
`subagent_results` para auditar si la respuesta vino de la KB, de los
conectores o de la búsqueda web.

---

## 6. Self-training (memoria que aprende)

1. Un caso resuelto se ingiere con `POST /api/v1/memory/ingest`:
   ```json
   { "payload": { "issue": "VPN no conecta en casa",
                  "resolution": "Registrar en AAD y resetear credenciales",
                  "priority": "P2" } }
   ```
2. La memoria episódica se guarda en Supabase (persistente).
3. En futuras consultas, `recall()` y el BM25 surface esa solución aprendida y
   el pipeline la fusiona con los resultados vectoriales.
4. Admins/agentes pueden añadir **case-studies** etiquetados.

---

## 7. Docker (alternativa local a producción propia)

```bash
export POSTGRES_PASSWORD=...
export JWT_SECRET_KEY=...
export ADMIN_EMAIL=...
export ADMIN_PASSWORD=...
export LLM_PROVIDER=google_gemini
export GOOGLE_API_KEY=...

docker compose up --build
# API: http://localhost:8000   |  UI: http://localhost:8501
```

---

## 8. Solución de problemas

| Síntoma                                   | Causa / solución                                        |
|-------------------------------------------|---------------------------------------------------------|
| `ConfigurationError`: GOOGLE_API_KEY      | La key falta o es placeholder; rellena `.env`/secret.   |
| `ValueError: JWT_SECRET_KEY ...`          | En prod debe tener 32+ caracteres.                      |
| `Rate limit exceeded (429)`               | Login 10/min, chat 60/min; sube `RATE_LIMIT_PER_MINUTE`.|
| Chat dice "no encontré información"       | Sin docs indexados ni memoria; usa `connectors/search` para verificar fuentes externas. |
| `DataError` fechas en Supabase            | Usar `DATABASE_URL` con `?ssl=require` y Postgres.      |
| Space HF "App not running"                | Dockerfile arranca en `$PORT`; revisa los secrets.      |
| Connectores devuelven vacío               | `CONNECTORS_ENABLED=true` + `GRAPH_*` válidos; revisa `GET /connectors/status`. |
| OAuth "provider not configured"           | Faltan `GOOGLE_OAUTH_*` / `MICROSOFT_OAUTH_*` en `.env`.|
| `ModuleNotFoundError` al instalar         | `pip install -r requirements.txt` en el venv.           |

---

## 9. Licencia

**MIT License** — Copyright (c) 2026 **Omar Pajares**.

Proyecto de código abierto y gratuito: puedes usarlo, modificarlo y
redistribuirlo libremente, incluso en empresas, con la única condición de
conservar el aviso de copyright. Ver [LICENSE](./LICENSE).