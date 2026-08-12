# Despliegue en la nube GRATIS (Hugging Face Spaces + Google Gemini)

Guía para publicar **HelpDesk Enterprise Copilot v12** en producción sin costo:
backend en **Hugging Face Spaces (Docker)**, base de datos y memoria en
**Supabase (gratis)**, LLM de **Google Gemini** (gratis), código en **GitHub**.

> Para conectar el agente a **Microsoft Copilot Studio**, ver
> [DEPLOY_COPILOT_STUDIO.md](./DEPLOY_COPILOT_STUDIO.md).

---

## 1. Publicar en GitHub

```bash
git init
git add .
git commit -m "HelpDesk Enterprise Copilot v12 — RAG + self-learning memory"
git branch -M main
git remote add origin https://github.com/<usuario>/helpdesk-copilot.git
git push -u origin main
```

> El `.gitignore` ya excluye `.env`, `data/`, `logs/`, `*.db` y caches. **Nunca**
> subas el `.env` ni credenciales.

## 2. Crear la base de datos en Supabase (gratis)

1. Crea un proyecto en https://supabase.com (plan **Free**: 500 MB, 10 000 filas).
2. Ve a **Project Settings → Database → Connection string → URI**.
3. Copia la URI compuesta y **traduce el parámetro SSL** de `?sslmode=require` a
   `?ssl=require` (asyncpg lo exige). Ejemplo:

```
postgresql://postgres.PROYECTO:CLAVE@aws-0-region.pooler.supabase.com:6543/postgres?ssl=require
```

4. Guárdala como `DATABASE_URL` en el entorno del Space (paso 3).

> El código ya usa columnas `DateTime(timezone=True)` compatibles con
> Postgres+asyncpg. Las tablas se crean automáticamente en el primer arranque
> (`init_db`).

## 3. Publicar en Hugging Face Spaces (backend + memoria)

1. Crea un Space en https://huggingface.co/new-space:
   - **SDK**: Docker
   - **Hardware**: CPU **Basic** (gratis, 2 vCPU / 16 GB RAM)
   - **Name**: `helpdesk-copilot`
2. Ve a **Settings → Repository secrets** y añade:

| Variable                       | Valor                                              |
|--------------------------------|----------------------------------------------------|
| `GOOGLE_API_KEY`               | `AIza...` (Gemini)                                  |
| `JWT_SECRET_KEY`               | 32+ caracteres aleatorios                           |
| `DATABASE_URL`                 | URI de Supabase (ver 2)                             |
| `ADMIN_EMAIL`                  | admin (o el que quieras)                            |
| `ADMIN_PASSWORD`               | contraseña fuerte del admin                         |
| `ENVIRONMENT`                  | `production`                                        |
| `LLM_PROVIDER`                 | `google_gemini`                                     |

3. Públicalo desde tu repo: **Settings → Connect to GitHub Repo** y elige
   `helpdesk-copilot`. El Space construirá el `Dockerfile` automáticamente.
4. La API quedará en:
   `https://<usuario>-helpdesk-copilot.hf.space` (la URL real se muestra en la
   pestaña App del Space). Comprueba `GET /api/v1/health`.

> **Importantes para el Space Docker:**
> - El `Dockerfile` arranca en el puerto `$PORT` (7860 por defecto), que es el
>   único puerto público que expone Hugging Face.
> - Los datos en disco del Space son **efímeros** (Chroma se pierde al
>   reconstruir). Por eso la BD y la memoria autocapacitada viven en **Supabase**.
>   El Space "se duerme" tras ~48 h de inactividad y despierta solo al recibir
>   una petición (la memoria sigue intacta en Supabase).

### 3.1 (Opcional) Rebuild/reprovisionar datos

Desde la pestaña **App** del Space puedes abrir el suiche **Restart** o
**Factory rebuild**; al arrancar `init_db()` rehace tablas y admin.

---

## 4. Conectores y OAuth (opcional)

Además de los secrets anteriores, si quieres activar conectores a tu entorno
Microsoft o login SSO, añade los secrets que correspondan:

| Variable                        | Valor                                                     |
|---------------------------------|-----------------------------------------------------------|
| `CONNECTORS_ENABLED`            | `true`                                                    |
| `GRAPH_TENANT_ID`               | Tenant de Entra ID                                        |
| `GRAPH_CLIENT_ID`               | App registration (client-credentials)                    |
| `GRAPH_CLIENT_SECRET`           | Secreto de la app                                         |
| `GOOGLE_OAUTH_CLIENT_ID`        | OAuth client de Google (para "Login with Google")         |
| `GOOGLE_OAUTH_CLIENT_SECRET`    | Secreto correspondiente                                   |

Los conectores comparten el registro de Entra con Graph; para SSO de
**Microsoft 365** usa `MICROSOFT_OAUTH_*`. Consulta `config/settings.py` para la
lista completa y `.env.example` para los nombres exactos.

> La búsqueda web (fallback cuando no hay documentación interna) está activada
> por defecto (`WEB_SEARCH_ENABLED=true`) y no necesita clave.

---

## 5. Verificación

```bash
curl https://<usuario>-helpdesk-copilot.hf.space/api/v1/health
# {"status":"ok",...}

# Estado de conectores/web:
curl -H "Authorization: Bearer $TOKEN" \
  https://<usuario>-helpdesk-copilot.hf.space/api/v1/connectors/status
```

Para probar el agente localmente antes de publicar: `python scripts/run_cli.py`
(modo interactivo) o `python scripts/run_ui.py` (UI Streamlit).