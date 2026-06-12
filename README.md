# DataForge AI

**An Autonomous AI Data Engineering Platform.**

Instead of "Where can I find a dataset?" users say **"I need a dataset for my task."**
The platform decides how to get the best dataset. **Generation is the last resort.**

## Core Philosophy

```
Search -> Evaluate -> Curate -> Merge -> Clean -> Translate -> Balance
      -> Generate (only if required) -> Benchmark -> Explain -> Export
```

Every component supports the same philosophy:

> Find existing data if possible. Improve it if needed. Generate only when there is a
> justified gap. Validate everything. Explain every decision.

## Frozen Architecture (Core)

- Search First / Generate Last
- Dynamic Planner (Workflow Library + legal mutations, never free-form graphs)
- Graph Validator (no invalid graph ever executes)
- Agent Registry (single source of truth; capability matrix is derived)
- Hybrid API Router (NIM preferred; Groq / Gemini / OpenAI / Ollama failover)
- Confidence Protocol (every agent output carries confidence + reason + next_action)
- Hard Gates (License, PII, Critical Toxicity) before any quality score
- Quality Scoring Framework (weighted metrics, see docs/QUALITY_FRAMEWORK.md)
- Explainability Agent (Auditor) -> Decision Trail + Explainability Report
- Dataset Intelligence Report + dataset.zip export

## Repository Structure

```
dataforge-ai/
  backend/        FastAPI app, core protocol, agent registry
  planner/        Workflow library, graph validator, execution engine
  agents/         Independent agents (discovery, curator, generator, ...)
  router/         Hybrid API Router (providers, policies, failover)
  reports/        Report generators (intelligence, explainability, quality)
  database/       Schema and migrations (PostgreSQL / Redis / Vector DB)
  frontend/       Next.js + React + Tailwind + shadcn/ui (separate workstream)
  config/         Settings and provider configuration
  deployment/     Docker / compose / deployment assets
  tests/          Unit and integration tests
  docs/           PRD, quality framework, architecture decisions
```

## Quickstart (backend)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

## Executable Product Slice

The backend now runs a deterministic end-to-end product slice:

```
Request -> RuleBasedPlanner -> Workflow Library -> Graph Validator
        -> Execution Engine -> Registry-backed agents
        -> Search -> License -> Merge -> Clean -> Translate -> Curate
        -> Quality -> Bias -> Validate -> Benchmark -> Reports -> Export
```

The Planner still never invents workflows. It selects a base Workflow Library entry,
then applies legal mutations such as removing optional translation for single-language
requests or removing optional bias checks for fast profiles. The mutated graph is
validated before execution.

Planner output includes machine-readable planning metadata:

```json
{
  "planner_confidence": 0.94,
  "planner_alternatives": ["clean_quality_export", "full_search_improve_export"],
  "planner_mutations": [
    {
      "action": "remove_optional_agent",
      "agent": "translation",
      "reason": "single_language_request"
    }
  ]
}
```

Agent Registry entries also expose dependency metadata (`requires`, `produces`),
category, estimated cost, and estimated runtime. This keeps the current Workflow
Library safe while preparing the Planner for capability/dependency graph building.

## Capability Cards

DataForge exposes machine-readable capability cards for the separate Planner and all
17 registry-backed execution agents:

```bash
curl http://127.0.0.1:8000/agents/cards
```

Each card includes mission, inputs, outputs, required/optional tools, constraints,
success criteria, standardized failure behavior, capability tags, dependencies,
state reads/writes, quality targets, events, cost, runtime, and parallelizability.
The Planner card is included for orchestration documentation but is not a registry
agent.

## Service Manifests

Deterministic support components are described separately from execution agents:

```bash
curl http://127.0.0.1:8000/services/manifests
```

Current service manifests cover report generation, dataset cards, manifests,
checksums, ZIP packaging, templates, and artifact storage. These services are invoked
by agents such as Packaging and Explainability but do not participate in the Agent
Registry. Each service is classified with `service_type`:

- `runtime`: executes during a workflow, such as reports, checksums, manifests, and ZIP packaging.
- `platform`: supports the system itself, such as artifact storage.

Packaging flow:

```text
PackagingAgent -> DatasetCardService -> ReportService -> ChecksumService
               -> ManifestService -> ZipService -> dataset.zip
```

Examples:

- Search-only: `requirement -> discovery -> license -> quality -> validator -> formatter -> packaging -> explainability`
- Cleaning-focused: `discovery -> license -> merge -> cleaning -> curator -> quality -> critic -> validator -> benchmark -> export`
- Multilingual: `cleaning -> curator -> translation -> quality -> bias -> critic -> validator -> export`
- Generation: `generator -> critic -> validator`, with generation used only when a workflow explicitly calls for it.

## Architecture Boundary

DataForge separates orchestration from execution:

- **Planner / Brain:** outside the Agent Registry. It selects Workflow Library entries,
  applies legal mutations, and sends validated graphs to the Execution Engine. It does
  not transform datasets.
- **17 registry-backed execution agents:** requirement analyzer, clarification,
  discovery, license, merge, cleaning, curator, translation, quality evaluator,
  generator, critic, validator, bias, benchmark, formatter, packaging, explainability.
- **Support services:** discovery providers, router, state manager, project store,
  report generators, artifact handling, cache, and provider manager. These are not
  workflow agents.

Start a workflow:

```bash
curl -X POST http://127.0.0.1:8000/workflow/start \
  -H "Content-Type: application/json" \
  -d '{"request":"I need a Hindi-English instruction dataset for healthcare."}'
```

The response includes the selected workflow, confidence-protocol agent messages,
report paths, and the generated `dataset.zip` path under `tmp/dataforge_runs/`.

Additional platform surfaces:

```bash
curl -X POST http://127.0.0.1:8000/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Healthcare Dataset","quality_profile":"production","target_model":"nemotron"}'
curl http://127.0.0.1:8000/projects
curl http://127.0.0.1:8000/agents/cards
curl http://127.0.0.1:8000/services/manifests
curl -X POST http://127.0.0.1:8000/discovery/search \
  -H "Content-Type: application/json" \
  -d '{"request":"I need an English-Hindi healthcare instruction dataset."}'
curl http://127.0.0.1:8000/discovery/providers
curl http://127.0.0.1:8000/workflows
curl http://127.0.0.1:8000/workflow/runs
curl http://127.0.0.1:8000/workflow/status/<task_id>
curl http://127.0.0.1:8000/router/status
curl http://127.0.0.1:8000/reports/<task_id>
curl -O http://127.0.0.1:8000/artifacts/<task_id>/dataset.zip
```

Local development persists project and run metadata in `tmp/dataforge_state.json`.
The repository boundary is isolated so it can be replaced with PostgreSQL without
changing planner, agent, or execution-engine code.

Live discovery is opt-in:

```powershell
$env:DATAFORGE_LIVE_DISCOVERY="true"
$env:GITHUB_TOKEN="<optional-token>"
$env:DATAFORGE_WEB_SEARCH_ENDPOINT="<optional-json-search-endpoint>"
```

When live discovery is disabled or a provider fails, DataForge keeps returning ranked
offline candidates from the local provider catalog.

## Documentation

- [Master PRD](docs/PRD.md) - Vision / Hackathon MVP / Demo Scope
- [Quality Scoring Framework](docs/QUALITY_FRAMEWORK.md) - the heart of the system

## Status

Architecture: **FROZEN**. All future ideas are roadmap items unless required for the demo.
