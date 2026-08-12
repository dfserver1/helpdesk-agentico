# Conexión a Microsoft Copilot Studio

Conecta el agente **HelpDesk Enterprise Copilot v12** a tu agente de **Microsoft
Copilot Studio** mediante un **Custom Connector de Power Platform**.

> El despliegue del backend (HF Spaces + Gemini gratis) se explica en
> [DEPLOY_GOOGLE.md](./DEPLOY_GOOGLE.md). Este documento solo cubre la
> integración con Copilot Studio.

---

## 1. Qué necesitas

- El backend publicado y accesible (URL tipo `https://<usuario>-helpdesk-copilot.hf.space`).
- La especificación OpenAPI 2.0 ya lista:
  **`docs/copilot_studio_openapi.json`** (formato **Swagger**, requerido por el
  custom connector de Power Platform).
- Un usuario/agente con rol `agent` o `admin` y su token JWT.

## 2. Crear el Custom Connector

1. Descarga `docs/copilot_studio_openapi.json`.
2. Abre **Power Automate / Power Apps** → **Data → Custom connectors → New →
   Import an OpenAPI file** y sube el archivo.
3. En **General**, revisa el **host** (debe ser la URL del Space, p. ej.
   `https://<usuario>-helpdesk-copilot.hf.space`). Ajusta basePath por defecto
   a `/api/v1` si el conector no lo toma del archivo.
4. En **Security** elige **API Key** → parámetro `Authorization`, ubicación
   `Header`.
5. En **Definition**, revisa las acciones disponibles:

   | Acción               | Endpoint                     | Descripción                                    |
   |----------------------|------------------------------|------------------------------------------------|
   | `AuthLogin`          | POST `/auth/login`           | Autenticarse (devuelve el token)              |
   | `Chat`               | POST `/chat`                 | Responder a una consulta                      |
   | `ChatDecide`         | POST `/chat/{id}/decide`     | Aprobar/rechazar ticket (HITL)                |
   | `TicketsList`        | GET `/tickets`               | Listar tickets                                |
   | `TicketsCreate`      | POST `/tickets`              | Crear ticket (calcula SLA)                    |
   | `MemoryIngest`       | POST `/memory/ingest`        | Enseñar al agente (self-training)             |
   | `MemoryRecall`       | POST `/memory/recall`        | Recuperar memoria aprendida                   |
   | `ConnectorsStatus`   | GET `/connectors/status`     | Estado de conectores O365/web                 |
   | `ConnectorsSearch`   | POST `/connectors/search`    | Buscar en SharePoint/Teams/Outlook/web        |

6. **Create + Test** una conexión con un token válido (paso 3).

## 3. Obtener el token del agente

El conector usa `Authorization: Bearer <token>`.

```bash
curl -s -X POST https://<usuario>-helpdesk-copilot.hf.space/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"agente@helpdesk.ai","password":"..."}' | jq -r .access_token
```

> **Tokens JWT:** expiran por defecto a los **60 min** (configurable con
> `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` en `.env`). Para un token permanente crea un
> usuario dedicado (rol `agent`) y renueva el token cuando caduque.

## 4. Usar el connector en Copilot Studio

1. En **Copilot Studio**: tu agente → **Tools → Add a tool → Connector**, elige
   el custom connector creado.
2. Asigna los parámetros:
   - `message` → "**Dynamically fill with AI**" para que el copilot extraiga el
     texto de la conversación.
   - `session_id` → opcional; déjalo dinámico para continuar conversaciones.
3. Guarda y prueba en el panel de test del agente.

## 5. Consideraciones de producción

- **Autenticación OAuth2 federada (Entra ID / Microsoft 365):** el código ya
  incluye la ruta OAuth para Microsoft (`/api/v1/auth/oauth/microsoft`), pero el
  custom connector con credenciales de aplicación requiere configuración extra
  de validación de tokens de Entra en `auth/` para un escenario de
  SSO empresarial. Para la mayoría de despliegues, **API Key con token JWT** es
  suficiente.
- **Rate limiting:** login 10/min, chat 60/min por IP. Si el copilot satura,
  sube `RATE_LIMIT_PER_MINUTE` en el entorno del Space.
- **Human-in-the-loop:** cuando `ChatResponse.needs_approval=true`, usa la
  acción `ChatDecide` con `decision=yes/no` para cerrar el ticket. El nuevo
  flujo responde con `used_connectors`, `used_web_search` y `subagent_results`
  para auditar de dónde salió la respuesta.
- **Concurrente:** el backend procesa varias sesiones en paralelo (semáforo
  global `MAX_CONCURRENT_SESSIONS=8`); Copilot Studio puede lanzar consultas
  simultáneas sin encolarse en el servidor.