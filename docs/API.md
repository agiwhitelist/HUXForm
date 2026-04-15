# AGUI API Reference

Base URL: `http://localhost:8001/api`

## Endpoints

---

### POST /api/chat

Send a chat message and receive a response.

**Request Body**

```json
{
  "messages": [
    { "role": "user", "content": "Hello" }
  ],
  "model": "openai",
  "session_id": "optional-session-id"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `messages` | array[Message] | Yes | List of chat messages |
| `model` | string | No | LLM model to use (defaults to configured model) |
| `session_id` | string | No | Session ID for conversation continuity |

**Message Object**

```json
{ "role": "user", "content": "string" }
```

| Field | Type | Description |
|-------|------|-------------|
| `role` | string | Message role: `"user"` or `"assistant"` |
| `content` | string | Message text |

**Response**

```json
{
  "message": { "role": "assistant", "content": "Response text" },
  "session_id": "session-id",
  "ui_document": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `message` | Message | Assistant's response message |
| `session_id` | string | Session ID used |
| `ui_document` | object | Optional UI document structure |

**Example curl**

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      { "role": "user", "content": "Show me my tasks" }
    ]
  }'
```

---

### POST /api/actions

Execute an action by ID.

**Request Body**

```json
{
  "action_id": "submit-form",
  "params": { "field": "value" },
  "session_id": "optional-session-id"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action_id` | string | Yes | Identifier of the action to execute |
| `params` | object | No | Parameters for the action (default: `{}`) |
| `session_id` | string | No | Session ID context |

**Response**

```json
{
  "success": true,
  "result": { ... },
  "error": null,
  "ui_document": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the action succeeded |
| `result` | any | Action result data on success |
| `error` | string | Error message on failure |
| `ui_document` | object | Optional UI document update |

**Example curl**

```bash
curl -X POST http://localhost:8000/api/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "navigate",
    "params": { "path": "/dashboard" }
  }'
```

---

### GET /api/sessions/{session_id}

Retrieve a session by ID.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | string | The session identifier |

**Response**

```json
{
  "session_id": "abc-123",
  "created_at": "2024-01-01T00:00:00Z",
  "status": "active"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `created_at` | string | ISO 8601 creation timestamp |
| `status` | string | Session status (`"active"`, `"archived"`, etc.) |

**Error Responses**

| Status | Detail |
|--------|--------|
| 404 | Session not found |

**Example curl**

```bash
curl http://localhost:8000/api/sessions/abc-123
```

---

### POST /api/sessions

Create a new session.

**Request Body**

None required.

**Response**

```json
{
  "session_id": "generated-uuid",
  "created_at": "2024-01-01T12:00:00Z",
  "status": "active"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Newly generated session UUID |
| `created_at` | string | ISO 8601 creation timestamp |
| `status` | string | Initial status (`"active"`) |

**Example curl**

```bash
curl -X POST http://localhost:8000/api/sessions
```

---

### GET /api/ui-schema

Get the UI schema defining available block and action types.

**Response**

```json
{
  "version": "1.0",
  "block_types": [
    "text", "stat", "card", "section", "list", "table",
    "chart", "form", "selector", "timeline", "image", "action_bar"
  ],
  "action_types": ["button", "link", "submit", "navigate"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Schema version |
| `block_types` | array[string] | Available UI block types |
| `action_types` | array[string] | Available UI action types |

**Example curl**

```bash
curl http://localhost:8000/api/ui-schema
```

---

## Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| 200 | Success |
| 400 | Bad Request — invalid request body |
| 404 | Not Found — resource does not exist |
| 422 | Validation Error — request validation failed |
| 500 | Internal Server Error |

All error responses include a `detail` field with the error message.
