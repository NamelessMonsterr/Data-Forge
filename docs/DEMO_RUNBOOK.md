# DataForge Demo Runbook

## Demo Goal

Show DataForge as an AI-powered dataset discovery platform:

1. Search datasets with natural language.
2. Open a ranked result and explain the AI recommendation.
3. Upload a dataset.
4. Process, index, and search it.
5. Download ready-to-use artifacts.

## 3-Minute Script

### 0:00-0:30 - Problem

Finding the right dataset is slow. Teams search many sources, inspect licenses and
metadata manually, clean files locally, then still need dataset cards, reports, and
export artifacts.

### 0:30-1:20 - AI Search

Use:

```text
Find datasets for diabetes prediction
```

Show:

- Ranked local and public results.
- AI summary.
- Recommendation explanation.
- Quality and semantic relevance signals.

Talk track:

> DataForge understands the request, searches local and public dataset sources,
> ranks candidates by relevance and quality, and explains why a dataset fits the
> task.

### 1:20-2:20 - Upload and Process

Upload:

```text
demo_datasets/healthcare_diabetes.csv
```

Show:

- Processing stepper.
- Rows, columns, duplicate count, quality score.
- Dataset indexed into catalog.
- Download ZIP.

Talk track:

> The same platform can ingest user data, normalize it, infer schema, compute
> quality signals, generate reports, create a manifest and checksums, and package
> everything into a ZIP.

### 2:20-3:00 - Search Uploaded Data + NVIDIA Story

Search:

```text
diabetes glucose outcome labels
```

Show the uploaded dataset in results.

Talk track:

> DataForge uses a skill-based AI layer. Dataset summary and recommendation skills
> ask for intelligence; the LLM orchestrator prefers NVIDIA NIM and can retry or
> fall back to compatible providers while keeping the same skill interface.

## Demo Prompts

- Find datasets for diabetes prediction
- Climate datasets for rainfall forecasting
- Customer churn datasets
- Indian traffic accident datasets
- Healthcare datasets with patient demographics

## Sample Uploads

- `demo_datasets/healthcare_diabetes.csv`
- `demo_datasets/traffic_accidents_india.csv`
- `demo_datasets/climate_rainfall.csv`

## Run Commands

Backend:

```powershell
uvicorn backend.app.main:app --reload
```

Frontend:

```powershell
cd frontend
python -m http.server 5173
```

Open:

```text
http://127.0.0.1:5173
```

## NVIDIA Setup

Optional real-provider mode:

```powershell
$env:NVIDIA_API_KEY="<your-nvidia-api-key>"
$env:NVIDIA_NIM_BASE_URL="https://integrate.api.nvidia.com/v1"
$env:NVIDIA_NIM_MODEL="meta/llama-3.1-70b-instruct"
$env:DATAFORGE_LLM_PROVIDERS="nim,gemini,openai,ollama"
```

Without credentials, the deterministic local provider keeps the demo reliable.

## Live Demo Checklist

- Backend health returns `200`.
- Frontend loads at `http://127.0.0.1:5173`.
- `/ai/llm/status` shows NIM first.
- Search returns at least one result.
- Upload sample CSV completes.
- ZIP download link works.
- Refreshing catalog still shows uploaded dataset.

## Fallback Plan

If public discovery is slow or unavailable:

1. Disable public search in the UI.
2. Upload `healthcare_diabetes.csv`.
3. Search for `diabetes glucose outcome labels`.
4. Show local catalog result, AI recommendation, schema, quality, and ZIP.

If NVIDIA API is unavailable:

1. Show `/ai/llm/status`.
2. Explain provider fallback.
3. Continue with deterministic local mode.
