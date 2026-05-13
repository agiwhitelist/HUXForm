# AGUI

> **AGUI** is a generative human-experience runtime for AI agents.
>
> User describes a task. AGUI **directs** a unique visual concept for it,
> generates a self-contained mini-app on the fly, and runs it inside a
> sandboxed iframe that talks to AGUI through a safe bridge.

Not a chat. Not a dashboard builder. Not a component library. Each task
gets its own interface, designed to fit the task — not a templated one.

```text
Intent → Plan + Visual Brief → Generated HTML/CSS/JS → Sandboxed iframe
       ↔ AGUI Bridge (postMessage) ↔ Tool Broker + Permission Layer
                                       ↳ built-in tools + MCP + OpenAPI + CLI
```

See [`idea.md`](./idea.md) for the long form.

## What's inside

### Backend (`apps/api`)
- `director.py` — **Director**. One LLM pass that produces (a) a presentation
  plan and (b) a structured *visual brief*: metaphor, palette, typography,
  layout, motion vocabulary, microcopy tone, banned defaults, real-world
  inspirations.
- `codegen.py` — **UI Generator**. Consumes the brief and emits a single
  self-contained HTML document. The system prompt actively forbids
  generic dark-SaaS templates.
- `executor.py` — **Tool Broker + Permission Layer**. Per-tool risk class
  determines whether a call runs unattended, needs approval, or supports
  dry-run.
- `tools.py` — built-in capabilities (`llm.ask`, `llm.structured`,
  `web.search`, `data.parse_csv`, `data.find_duplicates`, `data.summarize`,
  `files.read`, `task.*`, optional `cli.*`).
- `mcp_client.py` — stdio MCP-client manager. Spawn servers from
  `.agui/mcp.json`, list their tools, register each as `mcp.<alias>.<name>`.
- `openapi_adapter.py` — Load any OpenAPI 3.x spec and expose every
  operation as `openapi.<alias>.<operationId>`.
- `narrator.py` — Watches each turn's event stream and emits
  human-friendly `narration` events (single-sentence summaries).
- `tasks.py` — Domain model: Thread → Turn → events / state / files.
- `persistence.py` — SQLite store with hydration on boot.
- `audit.py` — Append-only audit log (tool calls, approvals).
- `runtime_stub.py` — The `window.agui` shim injected into every served
  document.

### Frontend (`apps/web`)
- Threaded workspace: each user message is a *turn*, AGUI's response is
  (plan card → generated iframe → live narration → final result).
- Composer at the bottom with file attachments (uploaded immediately).
- Plan steering: when AGUI proposes a non-trivial plan, you can Proceed
  or Cancel before codegen burns tokens.
- Per-turn Inspector with raw event stream.
- Approval overlay (both for backend tool approvals and iframe-initiated
  `agui.askApproval` requests).

## Why "non-template"

A normal LLM-generated UI converges on the same generic look:
three-column dark cards, a sidebar, a hamburger, glassmorphism panels.
That makes every task feel the same. AGUI fights this in two places:

1. **The Director outputs a visual brief** with a concrete *metaphor*
   (a duplicate-finder bench, a sonar sweep, a reading room) plus a
   palette and an explicit list of banned defaults.
2. **The UI Generator system prompt** treats the brief as a constraint
   and explicitly forbids the common defaults.

Result: a CSV cleaner doesn't look like an influencer scout, which
doesn't look like a deploy console.

## Provider configuration

AGUI is provider-agnostic. Pick the protocol your provider speaks:

| Var                   | Default                              | Notes                                  |
|-----------------------|--------------------------------------|----------------------------------------|
| `AGUI_LLM_PROTOCOL`   | `anthropic`                          | `anthropic` (Messages) or `openai`     |
| `AGUI_LLM_BASE_URL`   | `https://api.minimax.io/anthropic`   | Provider base URL.                     |
| `AGUI_LLM_MODEL`      | `MiniMax-M2`                         | Model id.                              |
| `AGUI_LLM_API_KEY`    | —                                    | API key.                               |
| `AGUI_LLM_MAX_TOKENS` | `4096`                               |                                        |
| `AGUI_LLM_TEMPERATURE`| `0.6`                                |                                        |
| `TAVILY_API_KEY`      | —                                    | If set, `web.search` uses Tavily.      |
| `AGUI_MCP_CONFIG`     | `.agui/mcp.json`                     | Optional MCP server config.            |
| `AGUI_DATA_DIR`       | `.agui-data`                         | SQLite + uploads live here.            |
| `AGUI_ENABLE_CLI`     | unset                                | Enables `cli.*` host-CLI tools.        |
| `AGUI_CLI_ALLOWLIST`  | unset                                | Optional `:`-separated allowlist.      |

## Bridge API (inside generated UI)

```js
agui.plan, agui.tools, agui.goal, agui.taskId, agui.files

await agui.callTool(name, params)          // run a registered tool
await agui.askApproval(label, details)     // request a one-off human OK
await agui.readFile(file_id)               // read an attached file
agui.setState(patch)
agui.getState()
agui.finalResult(value)
agui.log(level, message)
agui.toast(message, kind)
agui.onEvent(handler)
```

Sandbox: `allow-scripts` only, **no** `allow-same-origin`, **no** network.
The bridge is the only way out of the iframe.

## MCP servers

Create `.agui/mcp.json`:

```json
{
  "servers": [
    { "alias": "fs",  "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"] },
    { "alias": "git", "command": "uvx", "args": ["mcp-server-git", "--repository", "."] }
  ]
}
```

On boot AGUI spawns each server, calls `tools/list`, and registers every
exposed tool as `mcp.<alias>.<tool>` in the AGUI Tool Registry —
immediately usable from any generated UI.

## OpenAPI

```bash
curl -X POST http://localhost:8001/api/tools/openapi -H 'content-type: application/json' -d '{
  "alias": "petstore",
  "spec_url": "https://petstore3.swagger.io/api/v3/openapi.json",
  "base_url": "https://petstore3.swagger.io/api/v3",
  "auth_header_name": "Authorization",
  "auth_header_value": "Bearer ..."
}'
```

Every operation becomes a callable tool.

## Run locally

```bash
cp .env.example .env  # put your key in AGUI_LLM_API_KEY

# backend
cd apps/api && python -m venv .venv && . .venv/bin/activate \
  && pip install -e . && uvicorn src.main:app --reload --port 8001
# frontend (separate terminal)
cd apps/web && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` → `http://localhost:8001`.

Docker:

```bash
docker compose up --build api web                   # dev (web :5173, api :8001)
docker build --target production -t agui .          # prod single-image (nginx + uvicorn)
```

## Endpoints

| Method | Path                                       | Purpose                                  |
|--------|--------------------------------------------|------------------------------------------|
| POST   | `/api/threads`                             | Create thread + first turn               |
| GET    | `/api/threads`                             | List threads                             |
| GET    | `/api/threads/{tid}`                       | Thread + ordered turns                   |
| POST   | `/api/threads/{tid}/turns`                 | Add a follow-up turn                     |
| GET    | `/api/turns/{tid}`                         | Snapshot                                 |
| GET    | `/api/turns/{tid}/ui`                      | Generated HTML (with runtime injected)   |
| GET    | `/api/turns/{tid}/events`                  | SSE event stream (replayable)            |
| POST   | `/api/turns/{tid}/tools/{name}`            | Run a tool (bridge target)               |
| POST   | `/api/turns/{tid}/approve`                 | Resolve a pending approval               |
| POST   | `/api/turns/{tid}/proceed`                 | Proceed past plan steering               |
| POST   | `/api/turns/{tid}/cancel`                  | Cancel a turn                            |
| POST   | `/api/files`                               | Upload a file                            |
| GET    | `/api/files/{fid}`                         | Download                                 |
| GET    | `/api/tools`                               | Registered tools                         |
| POST   | `/api/tools/openapi`                       | Register an OpenAPI spec                 |
| GET    | `/api/audit?turn_id=&limit=`               | Audit tail                               |
