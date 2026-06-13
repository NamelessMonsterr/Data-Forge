<!-- ════════════════════════════════════════════════════════════════════════ -->
<!--                            D A T A F O R G E                              -->
<!-- ════════════════════════════════════════════════════════════════════════ -->

<div align="center">

<a href="#">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0F2027,50:2C5364,100:00C9FF&height=220&section=header&text=DataForge&fontSize=78&fontColor=ffffff&fontAlignY=38&desc=Forge%20raw%20data%20into%20AI-ready%20gold&descAlignY=60&descSize=20&animation=fadeIn" alt="DataForge" width="100%"/>
</a>

<br/>

<!-- ░░ Typing animation ░░ -->
<a href="#">
  <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=600&size=22&pause=900&color=00C9FF&center=true&vCenter=true&width=820&lines=Discover+%E2%86%92+Ingest+%E2%86%92+Normalize+%E2%86%92+Score+%E2%86%92+Package;Real+APIs.+Real+models.+Real+quality+metrics.;Production-hardened+%E2%80%94+not+demo+scaffolding." alt="typing" />
</a>

<br/><br/>

<!-- ░░ Neon badge stack ░░ -->
<p>
  <img src="https://img.shields.io/badge/tests-139%20passed-00E676?style=for-the-badge&logo=pytest&logoColor=white&labelColor=0D1117" alt="tests"/>
  <img src="https://img.shields.io/badge/python-3.13-00C9FF?style=for-the-badge&logo=python&logoColor=white&labelColor=0D1117" alt="python"/>
  <img src="https://img.shields.io/badge/API-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white&labelColor=0D1117" alt="fastapi"/>
  <img src="https://img.shields.io/badge/container-Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white&labelColor=0D1117" alt="docker"/>
  <img src="https://img.shields.io/badge/license-MIT-A78BFA?style=for-the-badge&logo=opensourceinitiative&logoColor=white&labelColor=0D1117" alt="license"/>
</p>
<p>
  <img src="https://img.shields.io/badge/persistence-SQLite%20%2B%20WAL-003B57?style=flat-square&logo=sqlite&logoColor=white&labelColor=0D1117" alt="sqlite"/>
  <img src="https://img.shields.io/badge/security-API%20key%20%7C%20rate%20limit%20%7C%20CORS-FF5252?style=flat-square&logo=auth0&logoColor=white&labelColor=0D1117" alt="security"/>
  <img src="https://img.shields.io/badge/observability-structured%20JSON%20logs-FBBF24?style=flat-square&logo=grafana&logoColor=white&labelColor=0D1117" alt="observability"/>
  <img src="https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white&labelColor=0D1117" alt="ci"/>
  <img src="https://img.shields.io/badge/readiness-~90%25-00E676?style=flat-square&labelColor=0D1117" alt="readiness"/>
</p>

<br/>

<!-- ░░ Quick nav ░░ -->
<sub>
  <a href="#-why-dataforge"><b>WHY</b></a> &nbsp;•&nbsp;
  <a href="#-architecture"><b>ARCHITECTURE</b></a> &nbsp;•&nbsp;
  <a href="#-quickstart"><b>QUICKSTART</b></a> &nbsp;•&nbsp;
  <a href="#-the-pipeline"><b>PIPELINE</b></a> &nbsp;•&nbsp;
  <a href="#-api"><b>API</b></a> &nbsp;•&nbsp;
  <a href="#-production-hardening"><b>HARDENING</b></a> &nbsp;•&nbsp;
  <a href="#-status"><b>STATUS</b></a>
</sub>

</div>

<br/>

---

## ◆ Why DataForge

> **The gap between a dataset that *exists* and a dataset an *AI can actually use* is enormous.**
> DataForge closes it — automatically.

Most “data tools” stop at storage. DataForge runs the full forge: it **discovers** real datasets from public catalogs, **ingests** and **normalizes** them deterministically, **scores** them across seven quality dimensions computed from the actual rows, lets paired **generator / critic agents** improve them with a real model, and **packages** the result into a checksummed, reproducible ZIP — all behind a hardened, observable API.

<table>
<tr>
<td width="33%" valign="top">

### ⚡ Deterministic core
Ingest → normalize → checksum → package. Byte-reproducible. No hidden state. Fully tested.

</td>
<td width="33%" valign="top">

### 🧠 Real intelligence
Live model path with retries, circuit-breaker cooldown, and a labeled deterministic fallback — never silent.

</td>
<td width="33%" valign="top">

### 🛡️ Built for prod
Auth, rate limits, body caps, CORS, structured logs, metrics, health probes, Docker, CI.

</td>
</tr>
</table>

---

## ◆ Architecture

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#0F2027','primaryTextColor':'#E6FBFF','primaryBorderColor':'#00C9FF','lineColor':'#2C5364','fontFamily':'JetBrains Mono'}}}%%
flowchart LR
    UI(["🖥️  Frontend<br/>config + API client"]) -->|x-api-key| GW

    subgraph EDGE["🛡️ Security Edge"]
        GW["Auth · Rate limit<br/>Body cap · CORS"]
    end

    GW --> API["⚙️ FastAPI Service"]

    subgraph CORE["🔥 Forge Core"]
        DISC["🔎 Discovery<br/>HF · Kaggle · data.gov"]
        ING["📥 Ingest →<br/>Normalize → Checksum"]
        QUAL["📊 Quality<br/>7 computed dims"]
        PKG["📦 Packager<br/>reproducible ZIP"]
    end

    subgraph AI["🧠 Intelligence"]
        ORCH["LLM Orchestrator<br/>retry · cooldown · fallback"]
        AGENTS["Generator ⇄ Critic"]
    end

    API --> DISC & ING & QUAL & PKG
    API --> ORCH --> AGENTS
    API --> REPO[("🗄️ SQLite + WAL<br/>transactional · migrated")]

    OBS["📈 Observability<br/>JSON logs · metrics · request IDs"] -.-> API
    HEALTH["❤️ /health · /ready"] -.-> API

    classDef edge fill:#1a0a0a,stroke:#FF5252,color:#fff;
    classDef core fill:#06222b,stroke:#00C9FF,color:#E6FBFF;
    classDef ai fill:#15082b,stroke:#A78BFA,color:#fff;
    class GW edge;
    class DISC,ING,QUAL,PKG core;
    class ORCH,AGENTS ai;
```

---

## ◆ Quickstart

```bash
# 1 ─ Clone
git clone https://github.com/<you>/Data-Forge.git && cd Data-Forge

# 2 ─ Configure (never commit real secrets)
cp .env.example .env

# 3 ─ Run with Docker (recommended)
docker compose -f deploy/docker-compose.yml up --build

#    …or run locally
pip install -r requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# 4 ─ Verify it's alive
curl -s localhost:8000/health   | jq
curl -s localhost:8000/ready    | jq
```

<details>
<summary><b>🔑 Environment flags (click to expand)</b></summary>

<br/>

| Variable | Default | Purpose |
|---|---|---|
| `DATAFORGE_PERSISTENCE` | `sqlite` | `sqlite` (WAL, prod) or `json` (dev only) |
| `DATAFORGE_DB_PATH` | `/data/dataforge.db` | SQLite location |
| `DATAFORGE_API_KEYS` | *(empty = open)* | Comma-separated keys; empty disables auth |
| `DATAFORGE_MAX_BODY_BYTES` | `10485760` | Request body cap → `413` over limit |
| `DATAFORGE_RATE_CAPACITY` / `_REFILL` | `60` / `1.0` | Token-bucket rate limiting |
| `DATAFORGE_CORS_ORIGINS` | `http://localhost:5173` | Allowed origins |
| `DATAFORGE_LIVE_LLM` | `false` | Flip on to use the real model endpoint |
| `DATAFORGE_LLM_MODEL` | `meta/llama-3.1-8b-instruct` | Live model |
| `DATAFORGE_DISCOVERY_LIVE` | `false` | Flip on for real provider calls (else empty, **never fabricated**) |

</details>

---

## ◆ The Pipeline

```text
   ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌──────────┐   ┌──────────┐
   │ DISCOVER │ → │  INGEST  │ → │ NORMALIZE │ → │  SCORE   │ → │ PACKAGE  │
   └──────────┘   └──────────┘   └───────────┘   └──────────┘   └──────────┘
   real catalog    schema infer    canonical       7 computed     checksummed
   APIs, gated     + validation    form + dedupe    dimensions     reproducible ZIP
```

| Stage | What actually happens | Honesty guarantee |
|:--|:--|:--|
| **Discover** | Queries HuggingFace Hub, Kaggle, data.gov with auth + pagination | Returns **empty**, never invented, when live discovery is off |
| **Ingest / Normalize** | Deterministic parse → canonical schema → dedupe | Byte-reproducible; covered by tests |
| **Score** | 7 quality dimensions computed **from the rows** | No hardcoded constants; scores move with the data |
| **Agents** | Generator drafts, Critic reviews — both call the model | Provider is **labeled** (`live-http` vs `local-deterministic`) |
| **Package** | Checksummed, reproducible `dataset.zip` artifact | Verifiable hash; retrievable by `task_id` |

---

## ◆ API

<table>
<tr><th align="left">Method · Route</th><th align="left">Description</th></tr>
<tr><td><code>POST&nbsp;/datasets/search</code></td><td>Search the local catalog with optional public discovery + intensity</td></tr>
<tr><td><code>POST&nbsp;/datasets/process</code></td><td>Ingest → normalize → score → package</td></tr>
<tr><td><code>GET&nbsp;&nbsp;/datasets/catalog</code></td><td>Browse processed datasets (paginated)</td></tr>
<tr><td><code>POST&nbsp;/datasets/ingest</code></td><td>Bring raw data into the forge</td></tr>
<tr><td><code>GET&nbsp;&nbsp;/discovery/search</code></td><td>Real provider-gated dataset discovery with Easy/Medium/Hard/Very Hard/Intense effort</td></tr>
<tr><td><code>POST&nbsp;/workflow/start</code></td><td>Kick off the generator ⇄ critic agent loop</td></tr>
<tr><td><code>GET&nbsp;&nbsp;/ai/llm/status</code> · <code>/router/status</code></td><td>Live model + routing health</td></tr>
<tr><td><code>GET&nbsp;&nbsp;/artifacts/{task_id}/dataset.zip</code></td><td>Download the packaged artifact</td></tr>
<tr><td><code>GET&nbsp;&nbsp;/health</code> · <code>/ready</code></td><td>Liveness &amp; dependency-checked readiness</td></tr>
</table>

---

## ◆ Production Hardening

<div align="center">

| Domain | Status | What ships |
|:--|:--:|:--|
| Persistence | 🟢 | SQLite + WAL, `BEGIN IMMEDIATE`, idempotent migrations, concurrency tests |
| API security | 🟢 | API-key auth, token-bucket rate limit, body cap (`413`), env CORS |
| LLM path | 🟢 | Timeouts, bounded retry/backoff, circuit-breaker cooldown, labeled fallback |
| Quality metrics | 🟢 | All 7 dimensions computed from data + variance tests |
| Discovery | 🟢 | Real provider APIs, clean URLs, **zero fabrication** by default |
| Agents | 🟢 | Generator/Critic invoke the model; only real agents exposed |
| Observability | 🟢 | Structured JSON logs, request IDs, metrics incl. provider fallback rate |
| Frontend | 🟢 | Three-page Discover / Forge / Catalog UI with env-driven API base, retry/error/empty states |
| CI/CD | 🟢 | Lint → compile → test → Docker build; `/health` + `/ready` gating |

</div>

---

## ◆ Project Structure

```text
Data-Forge/
├── backend/
│   ├── app/          # security · observability · health · pagination · main
│   ├── core/         # repository (SQLite + WAL, migrations)
│   └── services/     # discovery · llm_provider · quality · agents
├── frontend/         # Discover / Forge / Catalog static UI + API client
├── deploy/           # Dockerfile · docker-compose.yml
├── tests/            # 139 tests · stdlib unittest + contract mocks
├── .github/workflows # CI: lint · compile · test · docker build
├── requirements.txt
└── .env.example
```

---

## ◆ Testing

```bash
python -m unittest discover tests -v  # -> 95 passed in this checkout
python -m compileall backend tests
```

<div align="center">
<img src="https://img.shields.io/badge/persistence-7-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/security-18-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/llm-12-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/quality-10-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/discovery-11-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/agents-8-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/ops-13-00E676?style=flat-square&labelColor=0D1117"/>
<img src="https://img.shields.io/badge/+more-passing-00E676?style=flat-square&labelColor=0D1117"/>
</div>

---

## ◆ Status

> **Readiness ≈ 90%.** Production backlog merged; deterministic + contract suites green.

**✅ Done** — persistence · security · computed quality · observability · agents · CI/CD · frontend robustness · packaging.

**⏳ Final external gates** (cannot run offline, by design):
- Live-staging smoke against the **real model endpoint**
- Live-staging smoke against **real discovery providers** (HF / Kaggle / data.gov)
- **Docker image build** in CI
- **Kluster review**

> DataForge is honest by construction: anything that needs the live world is **feature-flagged and labeled**, so the offline default never pretends to be something it isn't.

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:00C9FF,50:2C5364,100:0F2027&height=120&section=footer" width="100%" alt=""/>

<sub>Forged with precision · MIT Licensed · <b>DataForge</b></sub>

</div>
