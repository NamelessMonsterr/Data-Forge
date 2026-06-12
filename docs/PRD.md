# DataForge AI - Master PRD (Frozen v2.0)

> Status: **ARCHITECTURE FROZEN**. No new core concepts. Every future idea is a roadmap
> item unless required for the demo.

---

## 1. Product Vision

DataForge AI is an autonomous AI Data Engineering Platform that intelligently discovers,
evaluates, curates, improves, **generates only when necessary**, validates, explains and
delivers production-ready datasets through dynamic multi-agent orchestration powered by
the NVIDIA AI ecosystem.

### Core Philosophy

Search -> Evaluate -> Curate -> Merge -> Clean -> Translate -> Balance ->
Generate (only if required) -> Benchmark -> Explain -> Export.

### Full Product Scope (vision)

- ~17 independent, message-based agents (Discovery, License, Curator, Merge, Cleaning,
  Translation, Balancing, Synthetic Generation, Bias, Critic, Validator, Benchmark,
  Formatter, Packaging, Explainability, Requirement Analyzer, Clarification)
- Planner (Brain): selects a base workflow from the Workflow Library, applies legal
  mutations, validates the graph, estimates cost/time/quality. **Never edits data.**
- Hybrid API Router: NVIDIA NIM, OpenAI, Anthropic, Gemini, Groq, Together AI, Ollama,
  HuggingFace, Custom. Policies: Fastest, Cheapest, Highest Quality, Balanced, Privacy,
  Custom Priority. Audited auto-failover.
- Quality profiles: Fast 70 / Balanced 80 / Production 90 / Research 95 / Enterprise 98.
- Deliverable: dataset.zip with dataset, metadata, dataset card, quality / bias /
  benchmark / license / explainability reports, statistics, Dataset Intelligence Report.
- Stack: Next.js + FastAPI + LangGraph/NeMo Agent Toolkit; PostgreSQL, Redis,
  Milvus/Qdrant/FAISS, Object Storage. NVIDIA: NIM, Nemotron, NeMo Curator, NeMo
  Retriever, Triton, TensorRT-LLM, CUDA.

---

## 2. Hackathon MVP (what we actually build)

Effective build window: **~7 days** (submission 19 June). The demo-critical path IS the MVP.

### In scope

| Component | Notes |
|---|---|
| Requirement Analyzer | NL -> structured spec |
| Dynamic Question Generator | minimal clarification questions |
| Planner | Workflow Library selection + legal mutations only (deterministic) |
| Graph Validator | rejects invalid graphs before execution |
| Agent Registry | single source of truth; capability matrix derived |
| Dataset Discovery | **HuggingFace Hub only** (Kaggle optional stretch) |
| License Validation | hard gate, with explanation on rejection |
| Curator (lite) | heuristic dedup/normalize/PII; NeMo Curator is the production path |
| Quality Evaluation | per docs/QUALITY_FRAMEWORK.md |
| Synthetic Generation | triggered only on justified gap |
| Critic + Validator | adversarial check + readiness check |
| Hybrid Router | NIM preferred; Groq, Gemini, OpenAI, Ollama must all work |
| Confidence Protocol | frozen envelope on every agent message |
| Explainability (Auditor) | decision trail for every major decision |
| Bias (lite) | distribution stats + toxicity pass (no industrial analysis) |
| Formatter + Packaging | JSON/JSONL/CSV + ZIP export |
| Dataset Intelligence Report | trimmed to metrics the MVP actually computes |

### Explicitly cut from MVP

Merge / Cleaning / Translation / Balancing agents, full NeMo Curator integration, Kaggle+
sources, auth beyond basic JWT, settings UI beyond API keys, "thousands of concurrent
requests" scalability claims, Benchmark agent (folded into Quality Evaluation).

### 7-day plan

- **Days 1-2:** walking skeleton end-to-end (request -> planner -> one workflow -> ZIP),
  stubbed agents. Always submittable from day 2.
- **Days 3-5:** replace stubs on the critical path (Discovery, Curator-lite, Quality,
  Generator, Critic/Validator, Router with 2-3 live providers).
- **Day 6:** scripted demo + Intelligence Report polish.
- **Day 7:** video, submission, buffer. Never zero.

---

## 3. Demo Scope (what the judges see)

Framing: **"Watch an AI Data Engineer work"** - not "build a dataset".
The demo is scripted and deterministic; the rejection is engineered, not accidental.

```
Judge types: "Need a commercial healthcare dataset."

Request Received
-> Planner selects workflow + mutations (graph shown live)
-> Searching HuggingFace...
-> Dataset found -> REJECTED: license conflict (hard gate, explained)
-> Searching again...
-> Partial match accepted -> Curating...
-> Gap analysis: need ~12% more examples
-> Synthetic generation (justified, logged)
-> Critic challenges -> Validator approves
-> Quality 9X% (Production gate passed)
-> Packaging -> Dataset Intelligence Report ready
-> Download dataset.zip
```

Slide 2 = the philosophy: competitors do "Need dataset -> Generate". We do
"Find -> Improve -> Merge -> Validate -> Export -> (no generation needed)".

---

## 4. Frozen Design Decisions

1. **Workflow Library + legal mutations.** Planner may: insert agent, remove optional
   agent, replace equivalent agent, reorder safe nodes. Planner may NOT: create node
   types, create cycles, remove mandatory validation. Graph Validator runs before every
   execution; invalid -> Planner regenerates.
2. **Quality spec before agent design.** Hard gates (License, PII, Critical Toxicity)
   are pass/fail OUTSIDE the score. Weighted score only after gates pass. See
   docs/QUALITY_FRAMEWORK.md.
3. **Agent Registry is the single source of truth.** The capability matrix is a derived,
   documentation-only view.
4. **Confidence Protocol.** Every agent returns result, confidence, reason, next_action
   where next_action is strictly one of: continue | retry | escalate | abort.
5. **Execution memory is Router-only (MVP).** Redis stores provider success rate, avg
   latency, avg cost, failure rate. The Router learns; the Planner does not (roadmap).
6. **Retry ladder:** retry -> different model -> different provider -> alternative
   workflow -> notify Planner -> continue. Every switch recorded by the Auditor.
7. **Stopping conditions:** quality met, max iterations, budget, timeout, cancellation.
   The Auditor records the reason.

---

## 5. Roadmap (post-hackathon)

Agent Marketplace, Dataset Marketplace, Dataset Digital Twin, Feedback Learning, Planner
Learning, Enterprise Collaboration / SaaS, Multi-modal, NVIDIA AI Foundry, DGX deployment.
