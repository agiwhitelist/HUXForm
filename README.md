# AGUI

> **AGUI** is a generative human-experience runtime for AI agents.
>
> User describes a task. AGUI decides how a human should see it happen,
> picks the right tools, and **generates a task-specific mini-app on
> the fly** that runs in a sandboxed iframe and talks to AGUI through a
> safe bridge.

Not a chat. Not a dashboard builder. Not a component library. Every task
gets its own interface.

```text
Intent → Tools → Execution → Human Experience
```

See [`idea.md`](./idea.md) for the long form.

## How it works

```
                ┌──────────────────────┐
   user intent  │  Presentation        │   plan + visual_concept
   ───────────► │  Planner   (LLM)     │ ───────────┐
                └──────────────────────┘            │
                                                    ▼
                                         ┌──────────────────────┐
                                         │  UI Generator        │
                                         │  (LLM → HTML/CSS/JS) │
                                         └─────────┬────────────┘
                                                   │
       ┌─────────────────────  generated HTML  ────┘
       │
       ▼
┌──────────────┐  postMessage  ┌──────────────────────┐  tools   ┌────────┐
│  sandboxed   │  ───────────► │  parent shell        │ ───────► │ Broker │
│  iframe      │  ◄─────────── │  (event stream / UI) │  ◄─────  │ + Perm │
└──────────────┘               └──────────────────────┘          └────────┘
```

Pieces:

- **`apps/api`** — FastAPI backend.
  - `planner.py` — Presentation Planner (decides mode + concept + steps).
  - `codegen.py` — UI Generator (LLM → self-contained HTML doc).
  - `executor.py` — Tool Broker + Permission Layer + Approval.
  - `tools.py` — Built-in capabilities the generated UI can call.
  - `tasks.py` — Task state + event stream (replayable, fan-out queue).
  - `runtime_stub.py` — `window.agui` shim injected into every generated doc.
  - `llm.py` / `config.py` — Provider-agnostic LLM client.
- **`apps/web`** — React/Vite shell. Renders the prompt screen, hosts the
  sandboxed iframe, proxies `postMessage` calls to the bridge, shows the
  event stream + approvals.

## Provider configuration

AGUI talks to any LLM that speaks one of the two common protocols. Configure
via env vars:

| Var                   | Default                                  | Notes                                          |
|-----------------------|------------------------------------------|------------------------------------------------|
| `AGUI_LLM_PROTOCOL`   | `anthropic`                              | `anthropic` (Messages API) or `openai` (Chat). |
| `AGUI_LLM_BASE_URL`   | `https://api.minimax.io/anthropic`       | Base URL of the provider.                      |
| `AGUI_LLM_MODEL`      | `MiniMax-M2`                             | Model id.                                      |
| `AGUI_LLM_API_KEY`    | —                                        | API key.                                       |
| `AGUI_LLM_MAX_TOKENS` | `4096`                                   |                                                |
| `AGUI_LLM_TEMPERATURE`| `0.6`                                    |                                                |

MiniMax M2 (Anthropic-compatible) is the default; switch to OpenAI / Groq /
OpenRouter / Together by changing the four `AGUI_LLM_*` vars.

## Run locally

```bash
cp .env.example .env  # then put your key in AGUI_LLM_API_KEY

# backend
cd apps/api && python -m venv .venv && . .venv/bin/activate \
  && pip install -e . && uvicorn src.main:app --reload --port 8001
# frontend (separate terminal)
cd apps/web && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` → `http://localhost:8001`.

Or, with Docker:

```bash
docker compose up --build api web        # dev: web on :5173, api on :8001
docker build --target production -t agui .   # prod single-image
```

## Bridge API (available inside generated UI)

```js
await agui.callTool(name, params)        // run a registered tool
await agui.askApproval(label, details)   // ask the human for a custom OK
agui.setState(patch)                     // merge into task state
agui.getState()                          // current snapshot
agui.finalResult(value)                  // mark task complete
agui.log(level, message)
agui.onEvent(handler)                    // subscribe to live events
agui.toast(message, kind)
agui.plan, agui.tools, agui.goal, agui.taskId
```

The generated document runs with `sandbox="allow-scripts"` and **no**
`allow-same-origin` — meaning no direct network, no cookies, no parent DOM
access. The bridge is the only way out.

## Built-in tools (MVP)

| Tool                   | Risk    | What                                                 |
|------------------------|---------|------------------------------------------------------|
| `llm.ask`              | read    | Free-form prompt to underlying LLM.                  |
| `llm.structured`       | read    | JSON output matching a schema hint.                  |
| `web.search`           | network | Simulated for now — plug in Tavily/Brave/SerpAPI.    |
| `data.parse_csv`       | read    | CSV → typed columns/rows.                            |
| `data.find_duplicates` | read    | Group rows by keys, return duplicate clusters.       |
| `data.summarize`       | read    | Per-column stats.                                    |
| `task.set_state`       | write   | Merge patch into task state (also emits event).      |
| `task.final_result`    | write   | Mark the task done with a result payload.            |
| `task.log`             | write   | Emit a log event to the stream.                      |

Adding tools is just another `_REGISTRY.register(Tool(...))` in `tools.py`.
MCP / CLI / OpenAPI adapters slot in here next.
