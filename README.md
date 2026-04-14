# AGUI — Universal Execution Interface Agent

A system that receives user intent, dynamically discovers/generates tools, maintains task state, and projects state into a dynamic UI via DSL.

## Structure

- /apps/api - FastAPI backend
- /apps/web - React frontend
- /packages - Core packages (llm-router, tool-registry, state-engine, ui-dsl, ui-renderer, orchestrator)