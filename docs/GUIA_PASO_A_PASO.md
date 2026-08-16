# Guía paso a paso — HelpDesk Enterprise Copilot

> Para quien recibe este proyecto por primera vez: cómo configurarlo, ejecutarlo
> en local, ponerlo en producción (gratis) y usarlo. Sin conocimientos previos
> de programación.

**Tiempo estimado total: 45–60 min** (la primera vez). Las cuentas que se crean
son **gratuitas** (Google AI Studio, GitHub, Hugging Face, Supabase).

---

## 0. Qué es esto (en 30 segundos)

Un **agente de soporte IT** con:

- **RAG** — responde preguntas basándose en la documentación que le des
  (recuperación híbrida BM25 + vectores + reranking).
- **Autoaprendizaje** — cada respuesta correcta se guarda en "memoria" y
  mejora sus futuras respuestas (memoria episódica persistente).
- **Conectores opcionales** — puede buscar en SharePoint/Teams/Outlook (Microsoft
  365) y en la web cuando no tiene documentación interna.
- **Multihilo** — atiende varias personas a la vez sin saturarse.
- **Tickets + SLA** — clasifica (P1–P4), asigna prioridad, calcula SLA y puede
  escalar a un humano con aprobación de ticket.

Hay **2 formas de usarlo**:
1. **Local** (tu propia máquina) — para probar y enseñárselo a otros.
2. **Producción gratis** (Hugging Face Spaces + Supabase) — accesible desde
   cualquier navegador y conectable a **Microsoft Copilot Studio**.

---

## 1. Requisitos previos (crear cuentas gratuitas)

| # | Qué                                | Para qué                                        | Cómo                                |
|---|------------------------------------|-------------------------------------------------|-------------------------------------|
| 1 | **Python 3.10+**                   | Ejecutar el código                              | https://www.python.org/downloads/   |
| 2 | **Git** (opcional)                 | Subir a GitHub                                  | https://git-scm.com/downloads       |
| 3 | **Cuenta Google AI Studio**        | API key de Gemini (LLM + embeddings gratis)     | https://aistudio.google.com/apikey  |
| 4 | **Cuenta GitHub**                  | Repositorio del código                          | https://github.com                  |
| 5 | **Cuenta Hugging Face**            | Alojar el backend en producción (Docker gratis) | https://huggingface.co/join         |
| 6 | **Cuenta Supabase**                | Base de datos en la nube (500 MB gratis)        | https://supabase.com                |

No necesitas **Docker local** si solo vas a probar en local; sí se necesita para
producción (lo construye Hugging Face automáticamente).

---

## 2. Paso 1 — Descomprimir y preparar el entorno (local)

1. Descomprime el zip en una carpeta, p. ej. `C:\HelpDeskCopilot`.
2. Abre una **terminal**:
   - Windows: menú Inicio → teclea `powershell` → Enter.
   - macOS/Linux: Terminal.
3. Ve a la carpeta del proyecto:
   ```bash
   cd C:\HelpDeskCopilot
   ```
4. Ejecuta el instalador automático (crea entorno virtual + dependencias + el
   archivo `.env` a partir de `.env.example`):
   ```bash
   python scripts/bootstrap.py
   ```
   > Si da la opción de instalar `pip`, acepta. Este paso tarda 2–5 min.

---

## 3. Paso 2 — Obtener la API key de Gemini (gratis)

1. Entra en https://aistudio.google.com/apikey
2. Pulsa **Create API key** → elige o crea un proyecto.
3. Copia la clave (empieza por `AIza...`).
4. Abre el archivo `.env` (con el bloc de notas) que creó el paso anterior y
   sustituye:
   ```
   GOOGLE_API_KEY=PASTE_YOUR_AI_STUDIO_KEY_HERE
   ```
   por
   ```
   GOOGLE_API_KEY=AIza...tu_clave_real
   ```
5. Guarda y cierra.

> ⚠️ No compartas este archivo `.env` con nadie. Es tu secreto.

---

## 4. Paso 3 — Crear el super-admin y arrancar en local

En la misma terminal:

```bash
python scripts/seed.py        # crea el usuario admin (idempotente)
python scripts/run_api.py     # arranca la API en http://localhost:8000
```

Deja esa terminal abierta. Abre una **segunda terminal** en la misma carpeta y
arranca la interfaz visual:

```bash
python scripts/run_ui.py      # interfaz en http://localhost:8501
```

Abre el navegador en **http://localhost:8501** → ya puedes usar el agente.

**Datos de acceso por defecto** (los que definiste en `.env`, sección `ADMIN_*`):
- Usuario: `admin@helpdesk.ai`
- Contraseña: la que pusiste en `ADMIN_PASSWORD`.

> En local también puedes usar el agente desde la terminal:
> ```bash
> python scripts/run_cli.py    # chat interactivo + estado de conectores
> ```

---

## 5. Paso 4 — Comprobar que funciona (fire-test)

> **Importante:** la base de conocimiento (KB) arranca vacía. La respuesta con
> **fuentes** solo aparece si la KB ya tiene documentos indexados. Dos formas
> de cargarla antes del fire-test:
>
> ```bash
> # (a) Memoria autocapacitada: enseña un caso desde UI → Self-Training
> # (b) Script de seed de documentos (si existe para tu despliegue):
> python scripts/seed.py
> ```
>
> Mientras la KB esté vacía, el chat responderá que no encontró información y
> propondrá abrir un ticket (flujo esperado, no un fallo).

1. Inicia sesión con el admin en la UI (http://localhost:8501).
2. En la pestaña **Chat**, escribe: *"¿Cómo restablezco una contraseña de
   Windows?"* y pulsa enviar.
3. Si la KB tiene contenido, deberías recibir una respuesta con **fuentes**.
   Si está vacía, el agente escalará a un ticket (correcto).
4. Ve a **Self-Training → Teach the agent** y guarda un caso:
   - *Issue:* `VPN no conecta en casa`
   - *Resolution:* `Registrar el equipo en AAD y resetear credenciales`
5. Repite la pregunta de la VPN → notarás que ahora usa la **memoria aprendida**.

> La suite de pruebas (opcional, valida todo) se ejecuta con:
> ```bash
> python -m pytest
> ```

---

## 6. Paso 5 — Ponerlo en PRODUCCIÓN (gratis)

### 6.1 Subir el código a GitHub

```bash
git init
git add .
git commit -m "HelpDesk Enterprise Copilot"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/helpdesk-copilot.git
git push -u origin main
```

> `.gitignore` ya excluye `.env`, `data/`, `logs/`, `*.db`. Nunca subas
> credenciales.

### 6.2 Crear la base de datos en Supabase

1. Entra a https://supabase.com → **New project** (plan Free).
2. Ve a **Project Settings → Database → Connection string → URI**.
3. Copia la URI y cambia `?sslmode=require` por `?ssl=require`:
   ```
   postgresql://postgres.PROYECTO:CLAVE@aws-0-region.pooler.supabase.com:6543/postgres?ssl=require
   ```
   La guardarás en el siguiente paso.

### 6.3 Publicar en Hugging Face Spaces

1. Crea un Space en https://huggingface.co/new-space:
   - **SDK**: Docker
   - **Hardware**: CPU **Basic** (gratis)
   - **Name**: `helpdesk-copilot`
2. En **Settings → Repository secrets**, añade:

   | Secret           | Valor                                          |
   |------------------|------------------------------------------------|
   | `GOOGLE_API_KEY` | `AIza...` (la misma de Gemini)                 |
   | `JWT_SECRET_KEY` | 32+ caracteres aleatorios (genera uno largo)   |
   | `DATABASE_URL`   | URI de Supabase (paso 6.2)                     |
   | `ADMIN_EMAIL`    | `admin@helpdesk.ai` (o el que quieras)         |
   | `ADMIN_PASSWORD` | contraseña fuerte del admin                    |
   | `ENVIRONMENT`    | `production`                                   |
   | `LLM_PROVIDER`   | `google_gemini`                                |

3. En **Settings → Connect to GitHub Repo** elige tu repositorio. El Space
   construye y despliega solo.
4. Al terminar, la API queda en:
   `https://<tu-usuario>-helpdesk-copilot.hf.space`
   Comprueba que responde: añade `/api/v1/health` al final en el navegador.

> La UI de producción (Streamlit) se abre añadiendo `/ui` a la misma URL
> (opcional; puedes usarla solo en local y en producción conectar la API a
> Copilot Studio).

> **Nota:** el contenedor de Hugging Face Space ejecuta **solo la API**; la UI
> Streamlit no se sirve en el Space. Para la UI en producción despliega el
> `ui/` por separado (p. ej. en Streamlit Community Cloud) apuntando a la URL
> de la API.

---

## 7. Paso 6 — Conectarlo a Microsoft Copilot Studio (opcional)

1. En Power Automate/Power Apps: **Data → Custom connectors → New → Import an
   OpenAPI file**, sube `docs/copilot_studio_openapi.json`.
2. **General**: revisa el host (debe ser `xxx.hf.space`).
3. **Security**: **API Key** → parámetro `Authorization`, ubicación `Header`.
4. **Test** con un token obtenido de `POST /api/v1/auth/login`.
5. En **Copilot Studio**: agente → **Tools → Add a tool → Connector** → elige el
   connector. Configura `message` como *"Dynamically fill with AI"*.

> Detalles completos y despliegue paso a paso:
> - `docs/DEPLOY_GOOGLE.md` — producción gratis.
> - `docs/DEPLOY_COPILOT_STUDIO.md` — integración con Copilot Studio.

---

## 8. Uso diario del agente

| Qué quieres hacer                         | Dónde                                                        |
|-------------------------------------------|--------------------------------------------------------------|
| Preguntar al agente                       | 🔁 Chat (UI) o `scripts/run_cli.py`                          |
| Enseñarle un caso resuelto                | 🧠 Self-Training → **Teach the agent**                       |
| Añadir un case-study etiquetado           | 🧠 Self-Training → **Case Study**                            |
| Ver tickets y SLA                         | 🎫 Tickets                                                   |
| Consultar la memoria aprendida            | 🧠 Self-Training → **Recall**                                |
| Ver estado de conectores                     | Chat con el agente: escribe `status` (CLI) o `GET /api/v1/connectors/status` |
| Aprobar un ticket escalado                | Responder `yes`/`no` cuando el agente lo pida                |

### Cómo alimentar su conocimiento (importante)

1. Método **automático**: cada vez que el agente resuelve, guarda la solución en
   memoria (self-training) para futuras consultas.
2. Método **manual**: en la UI, pestaña Self-Training, "Teach the agent" (issue +
   resolution). Es la mejor forma de entrenarlo con casos reales de tu equipo.

---

## 9. Solución de problemas frecuentes

| Síntoma                                        | Solución                                                        |
|------------------------------------------------|-----------------------------------------------------------------|
| Error: `GOOGLE_API_KEY`                        | Revisa que en `.env` / secrets la clave esté completa (`AIza...`). |
| `JWT_SECRET_KEY` error                         | En producción debe tener 32+ caracteres.                        |
| `Rate limit exceeded (429)`                    | Normal bajo muchas peticiones; sube `RATE_LIMIT_PER_MINUTE`.    |
| Responde "no encontré información"             | Aún no tiene documentación; enséñale casos en Self-Training.    |
| Space HF "App not running"                     | El Dockerfile arranca en `$PORT`; revisa los secrets del Space. |
| Conectores vacíos                              | `CONNECTORS_ENABLED=true` + `GRAPH_*` válidos; mira `GET /api/v1/connectors/status`. |
| OAuth "provider not configured"                | Faltan las claves `GOOGLE_OAUTH_*` / `MICROSOFT_OAUTH_*`.       |

---

## 10. Checklist final antes de producción

- [ ] `GOOGLE_API_KEY` real y funcional (probada en local).
- [ ] `.env` **nunca** subido a GitHub (solo `.env.example`).
- [ ] `JWT_SECRET_KEY` de 32+ caracteres en los secrets del Space.
- [ ] `DATABASE_URL` de Supabase con `?ssl=require`.
- [ ] Admin probado en local antes de publicar.
- [ ] (Opcional) Conector importado y probado en Copilot Studio.

---

## 11. Arquitectura (para referencia técnica)

```
UI (Streamlit)  ──▶  API (FastAPI, JWT+RBAC)
                        │
                        ▼
                  Agente LangGraph (RAG correctivo)
                  ├─ clasificación ITSM P1–P4 + SLA
                  ├─ recuperación híbrida (BM25 + vectores + rerank)
                  ├─ memoria autocapacitada (episódica) ──▶ PostgreSQL
                  ├─ investigación externa (sub-agentes paralelos)
                  └─ conectores O365 (Graph) + búsqueda web
                        │
                        ▼
              Tickets + SLA + aprobación humana
```

> Guías detalladas: `docs/DEPLOY_GOOGLE.md` y `docs/DEPLOY_COPILOT_STUDIO.md`.
> Especificación del conector: `docs/copilot_studio_openapi.json`.