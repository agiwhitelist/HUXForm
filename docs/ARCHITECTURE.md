# AGUI Architecture

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                  UI Layer                                    │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐                  │
│   │  Web    │    │ Terminal│    │  API    │    │  MCP    │                  │
│   │  Client │    │  UI     │    │  Client │    │  Client │                  │
│   └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘                  │
└────────┼──────────────┼──────────────┼──────────────┼───────────────────────┘
         │              │              │              │
         └──────────────┴──────┬───────┴──────────────┘
                               │
                          API Gateway
                               │
┌──────────────────────────────┼──────────────────────────────────────────────┐
│                         Orchestrator                                         │
│  ┌─────────────────┐    ┌─────────────┐    ┌─────────────────┐             │
│  │ IntentClassifier│───▶│   Planner   │───▶│  UIGenerator    │             │
│  │  (intent.py)    │    │ (planner.py) │    │(ui_generator.py)│             │
│  └─────────────────┘    └──────┬──────┘    └─────────────────┘             │
│                                │                                             │
│                     ┌──────────┴──────────┐                                 │
│                     │   ToolRegistry      │                                 │
│                     │ (tool_registry/src) │                                 │
│                     └──────────┬──────────┘                                 │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ▼                      ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  LLM Router     │  │  State Engine   │  │  Tool Discovery │
│ (llm_router/)   │  │ (state_engine/) │  │  Sources        │
│                 │  │                 │  │                 │
│ - Anthropic    │  │ - AgentState    │  │ - MCP servers   │
│ - OpenAI        │  │ - Checkpointing │  │ - Web search    │
│ - MiniMax       │  │ - Store         │  │ - Code generation│
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## Package Structure

```
agui/
├── packages/
│   ├── orchestrator/              # Core orchestration engine
│   │   └── src/
│   │       ├── orchestrator.py     # Main Orchestrator class
│   │       ├── intent.py            # IntentClassifier, IntentType
│   │       ├── planner.py           # Planner, PlannedTask, TaskStatus
│   │       └── ui_generator.py      # UI document generation
│   │
│   ├── state_engine/                # Agent state management
│   │   └── src/
│   │       ├── __init__.py          # Exports: AgentState, Task, Message,
│   │       │                         #   TaskResult, Observation, StateStore,
│   │       │                         #   CheckpointManager, DependencyTracker,
│   │       │                         #   MemoryBridge, ActionLoop
│   │       ├── models.py            # AgentState (TypedDict), Task, Message,
│   │       │                         #   TaskResult, Observation
│   │       ├── store.py              # StateStore - persistent state storage
│   │       ├── checkpoint.py         # CheckpointManager, CheckpointMode
│   │       ├── dependency.py         # DependencyTracker
│   │       ├── memory.py             # MemoryBridge
│   │       └── action_loop.py        # ActionLoop
│   │
│   ├── tool_registry/                # Tool management and discovery
│   │   └── src/
│   │       ├── registry.py           # ToolRegistry, ToolDefinition, ToolState
│   │       ├── discovery.py          # DiscoverySource, MCP/WebSearch/CodeGen
│   │       ├── lifecycle.py          # Tool lifecycle management
│   │       ├── code_generator.py     # Code generation for tools
│   │       ├── mcp_client.py         # MCP protocol client
│   │       └── models.py             # Tool models
│   │
│   ├── llm_router/                   # Multi-provider LLM routing
│   │   └── src/
│   │       ├── router.py             # LLMRouter - routes to providers
│   │       ├── providers.py          # Base provider interface
│   │       ├── anthropic_provider.py # Anthropic Claude provider
│   │       ├── openai_provider.py    # OpenAI GPT provider
│   │       ├── minimax_provider.py   # MiniMax provider
│   │       └── registry.py           # Provider registry
│   │
│   ├── ui_dsl/                       # UI definition language
│   └── ui_renderer/                  # UI rendering engine
│
└── docs/
    └── ARCHITECTURE.md              # This file
```

## Data Flow

### Request Processing Flow

```
User Input
    │
    ▼
┌─────────────────┐
│ IntentClassifier│  ── classifies input into IntentType
│ (intent.py)    │     (query/action/create/modify/delete/search/help)
└────────┬────────┘
         │ Intent
         ▼
┌─────────────────┐
│     Planner     │  ── creates PlannedTask list from intent
│ (planner.py)    │     maps IntentType to tool_name
└────────┬────────┘
         │ list[PlannedTask]
         ▼
┌─────────────────┐
│  ToolRegistry   │  ── executes tasks via registered handlers
│ (tool_registry) │
└────────┬────────┘
         │ TaskResult list
         ▼
┌─────────────────┐
│   Orchestrator  │  ── builds AgentState from completed tasks
│ (orchestrator.py)  ── checkpoints state via CheckpointManager
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  UIGenerator    │  ── generates UI document from task results
│ (ui_generator) │
└────────┬────────┘
         │
         ▼
      Response
      { intent, tasks, ui_document, session_id }
```

### State Flow

```
AgentState (TypedDict)
    │
    ├── messages: Annotated[list, add]    # Immutable append-only
    ├── current_task: Task | None
    ├── task_queue: list[Task]
    ├── completed_tasks: list[TaskResult]
    ├── observations: dict[str, Observation]
    ├── pending_actions: list[str]
    ├── memory_snapshot: str | None
    ├── loop_count: int
    ├── last_checkpoint: str | None
    └── state_version: int

State Persistence:
    StateStore ──► CheckpointManager ──► Async checkpoint save/restore
```

## Key Design Decisions

### 1. Intent-Based Planning

User input is classified into `IntentType` enum values (query, action, create, modify, delete, search, help, unknown) before planning. This separation allows:

- IntentClassifier to be swapped/replaced without affecting the planner
- Multiple intent types can map to the same tool with different parameters
- Confidence scores enable fallback handling

### 2. Tool Registry Pattern

The `ToolRegistry` acts as a central hub for all executable functionality:

- **Discovery sources** (MCP, WebSearch, CodeGen) dynamically populate tools
- **Lifecycle states** (discovered, registered, available, executing, success, failed) track tool status
- **Handler pattern** allows any callable to be registered as a tool
- Built-in `llm` tool routes to the configured LLM router

### 3. LangGraph-Style State Management

`AgentState` uses Python's `TypedDict` with `Annotated[list, add]` for immutable list updates:

- Messages can only be appended, never mutated in place
- Enables time-travel debugging and checkpointing
- `AgentState` is a pure data structure, not a class with methods

### 4. Checkpoint-Based Persistence

The `CheckpointManager` provides crash recovery:

- `CheckpointMode.SYNC` saves state synchronously after each task
- State includes completed tasks, observations, and memory snapshot
- On startup, `Orchestrator` restores from the latest checkpoint automatically

### 5. Multi-Provider LLM Routing

The `LLMRouter` abstracts away provider specifics:

- Supports Anthropic, OpenAI, and MiniMax
- Provider can be swapped via configuration
- Response is normalized to a common interface

### 6. UI Generation as a Separate Concern

`UIGenerator` transforms task results into UI documents:

- Output is a serializable `ui_document` dict
- Separates rendering logic from orchestration logic
- Supports multiple UI targets (web, terminal, API response)

## Dependencies Between Packages

```
orchestrator ──────► state_engine    (AgentState, CheckpointManager, StateStore)
orchestrator ──────► tool_registry  (ToolRegistry for execution)
orchestrator ──────► llm_router     (IntentClassifier uses it optionally)
tool_registry ─────► llm_router      (LLM tool handler routes through it)
state_engine       (standalone - no dependencies on other packages)
llm_router         (standalone - no dependencies on other packages)
```
