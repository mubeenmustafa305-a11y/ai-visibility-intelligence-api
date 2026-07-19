# AI Visibility Intelligence API

## 1. Project Overview

The **AI Visibility Intelligence API** is a RESTful Flask backend that helps businesses understand opportunity in AI-assistant search behaviour. It lets a user:

1. Register a business profile (domain, industry, competitors).
2. Run a synchronous three-agent pipeline that discovers commercially relevant queries, scores visibility opportunity, and generates content recommendations.
3. List, filter, and re-score discovered queries over time.

This project implements the **Python Developer Technical Assessment** (AI Visibility & Search Intelligence API). It is a simplified assessment backend—not a production SaaS.

**In scope:** Flask REST API, SQLAlchemy persistence, three LLM agents, DataForSEO for real SEO metrics, synchronous pipeline, tests, Docker Compose, and this README.

**Out of scope (intentional):** authentication, async/background jobs, status polling, rate limiting, frontend UI.

**Technologies used**

| Area | Technology |
|------|------------|
| Framework | Flask (`create_app()` factory) |
| ORM / migrations | SQLAlchemy, Flask-SQLAlchemy, Flask-Migrate (Alembic) |
| Database | SQLite (default), PostgreSQL optional |
| LLM | OpenAI and/or Anthropic via a shared client protocol |
| SEO data | DataForSEO (search volume, competition, organic SERP) |
| HTTP client | `requests` |
| Config | `python-dotenv` / `.env` |
| Tests | `pytest` with mocked LLM and DataForSEO |
| Runtime (Docker) | Gunicorn |

---

## 2. Architecture

```
HTTP (Flask blueprints)
        │
        ▼
   Services (profile, query, pipeline persistence)
        │
        ▼
 PipelineOrchestrator  ──►  Agents (discovery / scoring / recommendation)
        │                          │
        │                          ├── LLMClient (OpenAI | Anthropic)
        │                          └── DataForSEOClient (real SEO data)
        ▼
   SQLAlchemy models + Alembic migrations
```

### Flask application factory

`app/__init__.py` exposes `create_app()`. It loads config from the environment, initialises extensions (`db`, `migrate`), registers error handlers and blueprints, and imports models so Flask-Migrate can discover metadata.

### Blueprint architecture

| Blueprint | Module | Routes |
|-----------|--------|--------|
| `profiles_bp` | `app/api/profiles.py` | profiles CRUD-ish + `/run` + queries/recommendations lists |
| `queries_bp` | `app/api/queries.py` | `/recheck` |

### SQLAlchemy

Models live under `app/models/`. UUID string primary keys, timezone-aware timestamps, JSON columns for competitors/keywords, and foreign keys with cascade deletes.

### Services layer

| Service | Role |
|---------|------|
| `ProfileService` | Create/get profiles and summary stats |
| `PipelineService` | Persist runs, queries, scores, recommendations |
| `PipelineOrchestrator` | Sequence agents only (no HTTP) |
| `QueryService` | List/filter/paginate queries; list recommendations; recheck |
| `LLMClient` / factories | OpenAI & Anthropic adapters |
| `DataForSEOClient` | Keyword metrics + organic SERP visibility |

### Agent layer

`app/agents/` — three independently injectable agents, shared `BaseAgent` JSON helper, prompt constants, typed dataclasses. Agents never import Flask or write to the database.

### Utility layer

`app/utils/` — opportunity score formula, LLM JSON extract/repair/retry, domain normalisation, datetime formatting.

### Database layer

SQLite by default (`DATABASE_URL=sqlite:///dev.db`, resolved to an absolute project path). PostgreSQL is supported by changing `DATABASE_URL` and installing `psycopg2-binary` (optional dependency noted in `requirements.txt`). Migrations under `migrations/`.

### External integrations

- **OpenAI** or **Anthropic** for agent LLM calls.
- **DataForSEO** for real search volume, competition index, and organic SERP domain visibility.

---

## 3. AI Agent Design

Agents are constructor-injected, independently testable, do not call each other, and do not persist data.

### Agent 1 — `QueryDiscoveryAgent`

| | |
|--|--|
| **Purpose** | Generate 10–20 realistic, commercially relevant questions users ask AI assistants in the business’s competitive space. |
| **Inputs** | `BusinessProfileInput` (name, domain, industry, description, competitors). |
| **Outputs** | `DiscoveryAgentResult`: list of `{query_text, commercial_intent}` plus `tokens_used`; `error` if invalid/failed. |
| **Failure behavior** | Malformed JSON → repair retry (bounded). Validation/LLM failure → `ok=False` with `error`. **Orchestrator treats Agent 1 failure as a hard pipeline failure** (`PipelineRun.status=failed`). |

### Agent 2 — `VisibilityScoringAgent`

| | |
|--|--|
| **Purpose** | Score one query for opportunity using **real** SEO data plus an LLM commercial-intent estimate. |
| **Inputs** | `query_text`, target `domain`, optional `commercial_intent_hint` (from Agent 1). |
| **Outputs** | `ScoredQueryResult`: volume, competitive difficulty (0–100), `domain_visible`, `visibility_position`, `commercial_intent`, `opportunity_score`, `tokens_used`. |
| **DataForSEO usage** | `get_keyword_metrics` (Google Ads search volume / `competition_index`) and `check_domain_visibility` (Google organic SERP live, depth 20). |
| **Commercial intent** | LLM returns `commercial_intent` (0–1) given the query and observed metrics. On LLM failure, falls back to the hint or `0.5` and still returns SEO-based scores when DataForSEO succeeded. |
| **Failure behavior** | SEO lookup failure → `ok=False` for that query. **Orchestrator continues other queries** (partial failure). Unscored rows stay at default zeros / `domain_visible=null` and are not counted in `queries_scored`. |

### Agent 3 — `ContentRecommendationAgent`

| | |
|--|--|
| **Purpose** | Generate 3–5 actionable content recommendations for top queries where the domain is **not** visible. |
| **Inputs** | Business name/domain/industry + list of `QueryForRecommendation` (`query_ref` = persisted query UUID, text, opportunity score). |
| **Outputs** | `RecommendationAgentResult`: recommendations with `content_type`, `title`, `rationale`, `target_keywords`, `priority`, `query_ref`. |
| **Failure behavior** | Parse/validation failure → `ok=False`. **Orchestrator soft-fails**: run still `completed`, empty recommendations, failure text recorded on `error_message`. Skipped entirely when no `domain_visible is False` candidates exist. |

### Prompt engineering (all agents)

- System prompt: persona, constraints, exact JSON schema.
- User prompt template: variable substitution.
- Repair prompt template: used on JSON/schema failure.
- `BaseAgent._complete_json` → parse/repair/validate → bounded retries (`LLM_MAX_RETRIES`, clamped to 0–3).
- Malformed LLM JSON never crashes the process; agents return typed error results.

### Pipeline orchestrator sequence

```
BusinessProfile
    → create PipelineRun (status=running)
    → Agent 1 (discover)
    → persist DiscoveredQuery rows
    → for each query: Agent 2 → persist score (continue on per-query failure)
    → select top not-visible queries
    → Agent 3 (if applicable) → persist ContentRecommendation rows
    → finalize PipelineRun (status, counts, tokens, timestamps)
    → HTTP response
```

### Partial failure handling (as implemented)

| Case | Behaviour |
|------|-----------|
| Agent 1 fails | `status=failed`; no scoring/recs; `error_message` set |
| One or more Agent 2 failures | Continue remaining queries; failed queries left unscored |
| All Agent 2 attempts fail after discovery | `status=completed`, `queries_scored=0`, soft note on `error_message` |
| No not-visible queries | Skip Agent 3; `status=completed` |
| Agent 3 fails | `status=completed`, empty recommendations, soft note on `error_message` |
| Fully successful | `status=completed`, `error_message=null` |

Tokens from all agent LLM calls are summed into `PipelineRun.tokens_used` when providers report usage.

---

## 4. API Endpoints

All responses are JSON. Auth is not implemented.

### `POST /api/v1/profiles`

**Purpose:** Register a business profile.

**Request**

```json
{
  "name": "Surfer SEO",
  "domain": "surferseo.com",
  "industry": "SEO Software",
  "description": "AI-powered SEO content optimization tool",
  "competitors": ["clearscope.io", "marketmuse.com", "frase.io"]
}
```

**Response `201`**

```json
{
  "profile_uuid": "...",
  "name": "Surfer SEO",
  "domain": "surferseo.com",
  "status": "created",
  "created_at": "2025-01-15T10:00:00Z"
}
```

**Status codes:** `201` created · `400` validation error.

---

### `GET /api/v1/profiles/{profile_uuid}`

**Purpose:** Retrieve profile plus summary stats (`total_queries_discovered`, `avg_opportunity_score`; average is `null` when there are no queries).

**Response `200`:** profile fields + `summary` object.

**Status codes:** `200` · `404` not found.

---

### `POST /api/v1/profiles/{profile_uuid}/run`

**Purpose:** Run the full synchronous pipeline (Agent 1 → 2 → 3). May take 10–30+ seconds.

**Response `200`**

```json
{
  "pipeline_run_uuid": "...",
  "status": "completed",
  "queries_discovered": 12,
  "queries_scored": 11,
  "top_opportunity_queries": [ /* up to 3 */ ],
  "recommendations": [ /* Agent 3 results */ ],
  "tokens_used": 1234,
  "error_message": null
}
```

`status` is `completed` or `failed`. Soft issues may appear in `error_message` while `status` remains `completed`.

**Status codes:** `200` · `404` profile not found.

---

### `GET /api/v1/profiles/{profile_uuid}/queries`

**Purpose:** List all discovered queries for a profile.

**Query params**

| Param | Description |
|-------|-------------|
| `min_score` | Minimum `opportunity_score` (0–1) |
| `status` | `visible` \| `not_visible` \| `unknown` |
| `page` | Page number (default 1) |
| `per_page` | Page size (default 20, max 100) |

Sorted by `opportunity_score` descending.

**Response `200`**

```json
{
  "items": [
    {
      "query_uuid": "...",
      "query_text": "...",
      "estimated_search_volume": 1200,
      "competitive_difficulty": 62,
      "opportunity_score": 0.81,
      "domain_visible": false,
      "visibility_position": null,
      "discovered_at": "..."
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 12,
    "total_pages": 1
  }
}
```

**Status codes:** `200` · `400` bad params · `404` profile not found.

---

### `GET /api/v1/profiles/{profile_uuid}/recommendations`

**Purpose:** List content recommendations for a profile.

**Response `200`**

```json
{
  "items": [
    {
      "recommendation_uuid": "...",
      "target_query_uuid": "...",
      "content_type": "blog_post",
      "title": "...",
      "rationale": "...",
      "target_keywords": ["..."],
      "priority": "high"
    }
  ]
}
```

**Status codes:** `200` · `404` profile not found.

---

### `POST /api/v1/queries/{query_uuid}/recheck`

**Purpose:** Re-run **Agent 2 only**, update persisted scores, return updated scoring data (+ `tokens_used`). Commercial intent is re-estimated (not stored as its own DB column).

**Status codes:** `200` success · `404` query not found · `502` scoring failed (DB row unchanged).

---

### Error envelope (all endpoints)

```json
{
  "error": {
    "code": "validation_error",
    "message": "...",
    "details": {}
  }
}
```

---

## 5. Database Schema

### `BusinessProfile` (`business_profiles`)

`uuid` (PK), `name`, `domain`, `industry`, `description`, `competitors` (JSON), `status`, `created_at`, `updated_at`

### `PipelineRun` (`pipeline_runs`)

`uuid` (PK), `profile_uuid` (FK), `status`, `queries_discovered`, `queries_scored`, `tokens_used`, `error_message`, `started_at`, `completed_at`

### `DiscoveredQuery` (`discovered_queries`)

`uuid` (PK), `profile_uuid` (FK), `run_uuid` (FK), `query_text`, `estimated_search_volume`, `competitive_difficulty`, `opportunity_score`, `domain_visible` (nullable = unknown), `visibility_position`, `discovered_at`

### `ContentRecommendation` (`content_recommendations`)

`uuid` (PK), `profile_uuid` (FK), `query_uuid` (FK), `content_type`, `title`, `rationale`, `target_keywords` (JSON), `priority`, `created_at`

### Relationships

```
BusinessProfile 1 ──* PipelineRun
BusinessProfile 1 ──* DiscoveredQuery
BusinessProfile 1 ──* ContentRecommendation
PipelineRun     1 ──* DiscoveredQuery
DiscoveredQuery 1 ──* ContentRecommendation
```

Cascade deletes are configured from parent to children.

---

## 6. Opportunity Score Formula

Implemented in `app/utils/scoring.py` as a pure deterministic function. Result is **clamped to [0.0, 1.0]** and rounded to 4 decimal places.

```
volume_score     = log1p(search_volume) / log1p(100_000)
difficulty_score = 1 - (competitive_difficulty / 100)   # difficulty in 0–100
visibility_gap   = 1.0 if domain_visible is False
                 | 0.2 if domain_visible is True
                 | 0.5 if domain_visible is None (unknown)

score = clamp(
  0.40 * volume_score +
  0.30 * difficulty_score +
  0.20 * visibility_gap +
  0.10 * commercial_intent,
  0, 1
)
```

| Factor | Weight | Why |
|--------|--------|-----|
| Search volume | 0.40 | Higher demand = larger opportunity (log-scaled so extreme volumes do not dominate). |
| Competitive difficulty | 0.30 | Lower difficulty = easier to capture. |
| Visibility gap | 0.20 | Not appearing at all is the strongest gap; already visible is low gap; unknown is neutral. |
| Commercial intent | 0.10 | Comparison/buying queries are slightly more valuable than pure informational ones. |

---

## 7. AI Model Selection

**Supported providers (exactly as implemented):**

| Provider | Config | Default model example |
|----------|--------|------------------------|
| OpenAI | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` | `gpt-4o` |
| Anthropic | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | set via `LLM_MODEL` |

**Why OpenAI (`gpt-4o`) is the default**

- Strong structured JSON adherence (OpenAI path uses `response_format=json_object`).
- Suitable quality for commercial query ideation and content recommendations.
- Clear token usage reporting for `tokens_used` aggregation.

**Why Anthropic is also supported**

- Same `LLMClient` protocol and prompts; switch via env only.
- Useful if an Anthropic key is preferred; prompts remain provider-agnostic.

No other LLM providers are implemented.

---

## 8. External APIs

### OpenAI

Used for chat completions when `LLM_PROVIDER=openai` (Agents 1–3).

### Anthropic

Used for Messages API completions when `LLM_PROVIDER=anthropic`.

### DataForSEO

Used by Agent 2 (and recheck) for **real** third-party data:

| Call | Endpoint (client path) | Used for |
|------|------------------------|----------|
| Keyword metrics | Google Ads search volume live | `estimated_search_volume`, `competitive_difficulty` (from `competition_index`) |
| Domain visibility | Google organic SERP live advanced | `domain_visible`, `visibility_position` |

**Important limitation (honest):**

> The current implementation uses **DataForSEO organic SERP visibility** as a **proxy** for “AI visibility.” DataForSEO does **not** directly expose whether a domain appears in ChatGPT / Claude / Perplexity answers. Organic SERP presence is a measurable stand-in for assessment purposes—it is **not** true AI-answer citation visibility.

---

## 9. Validation and Error Handling

### Request validation

Manual validators in `app/api/validators.py` and `QueryListParams` (not Pydantic/Marshmallow). Profile create validates required strings, domain format, competitor list, and max lengths. Query list validates `min_score`, `status`, `page`, `per_page`.

### JSON parsing (LLM)

`app/utils/json_parser.py`: extract fenced/raw JSON → `json.loads` → light repair (trailing commas / simple quote fix) → schema key checks. Never raises to callers; returns `JsonParseResult`.

### Malformed LLM recovery

Agents call `parse_llm_json_with_retry` with a repair prompt. Retries are bounded (`max_retries` clamped to 0–3). Persistent failure becomes an agent `error` result, not a process crash.

### HTTP error envelope

Consistent `{ "error": { "code", "message", "details" } }` via `app/api/errors.py` for HTTP and unexpected exceptions.

### Partial / agent failures

Documented in §3 (orchestrator table). Recheck returns `502` on Agent 2 failure without updating the row.

---

## 10. Configuration

Copy `.env.example` → `.env`. Use placeholders only in examples—never commit real secrets.

| Variable | Purpose |
|----------|---------|
| `FLASK_APP` | `wsgi:app` |
| `FLASK_ENV` | e.g. `development` |
| `SECRET_KEY` | Flask secret (`change-me` placeholder) |
| `DATABASE_URL` | e.g. `sqlite:///dev.db` or Postgres URL |
| `LLM_PROVIDER` | `openai` or `anthropic` |
| `LLM_MODEL` | e.g. `gpt-4o` |
| `OPENAI_API_KEY` | Required if using OpenAI |
| `ANTHROPIC_API_KEY` | Required if using Anthropic |
| `LLM_TIMEOUT_SECONDS` | LLM HTTP timeout |
| `LLM_MAX_RETRIES` | JSON repair retries (default `1`) |
| `DATAFORSEO_LOGIN` | DataForSEO login |
| `DATAFORSEO_PASSWORD` | DataForSEO password |
| `DATAFORSEO_BASE_URL` | Default `https://api.dataforseo.com` |
| `DATAFORSEO_LOCATION_CODE` | Default `2840` (US) |
| `DATAFORSEO_LANGUAGE_CODE` | Default `en` |
| `DATAFORSEO_TIMEOUT_SECONDS` | DataForSEO HTTP timeout |

---

## 11. Running the Project

### Prerequisites

Python 3.11+ (3.12 recommended), OpenAI or Anthropic API key, DataForSEO credentials (for `/run` and recheck).

### Local setup

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# edit .env with your keys (never commit .env)

# Windows
$env:FLASK_APP = "wsgi:app"
# macOS / Linux
export FLASK_APP=wsgi:app

flask db upgrade
flask run --host 0.0.0.0 --port 5000
```

### Docker Compose

```bash
cp .env.example .env
# fill secrets in .env

docker compose up --build
```

API: `http://localhost:5000`. Entrypoint runs `flask db upgrade`, then Gunicorn with a 120s timeout for the sync pipeline. SQLite data is stored in the `api-data` volume.

### Running tests

```bash
pip install -r requirements.txt
pytest
```

---

## 12. Testing

**Current result:** **59** tests passing (`pytest`).

| Area | Files (examples) |
|------|------------------|
| Agent logic (mocked LLM) | `test_discovery_agent.py`, `test_scoring_agent.py`, `test_recommendation_agent.py` |
| Pipeline orchestrator | `test_pipeline_orchestrator.py` |
| HTTP endpoints | `test_phase5_endpoints.py`, `test_profile_http_endpoints.py` |
| Opportunity score | `test_scoring.py` |
| JSON parser / retry | `test_json_parser.py` |
| DataForSEO client parsing | `test_dataforseo_client.py` (mocked HTTP) |

External LLM and DataForSEO calls are **mocked** in unit/endpoint tests. Live API keys are not required to run the suite.

---

## 13. Engineering Decisions

These decisions match the current code:

1. **Synchronous pipeline** — assessment allows sync; simpler to reason about and demo.
2. **SQLite default** — zero-ops cold start; Postgres optional via `DATABASE_URL`.
3. **Manual request validation** — Pydantic/Marshmallow not added (bonus only).
4. **UUID string primary keys** — portable across SQLite/Postgres.
5. **Thin orchestrator** — agents own AI work; `PipelineService` owns persistence; API owns HTTP.
6. **No authentication** — assessment marks auth out of scope.
7. **SERP visibility as proxy** — real DataForSEO data without inventing AI-citation APIs.
8. **Agent 2 commercial intent via LLM** — volume/difficulty/visibility stay real; intent is LLM-estimated.
9. **Per-query commits after scoring** — long runs retain partial progress.
10. **`query_ref` = query UUID** — Agent 3 recommendations map cleanly to FK rows.

---

## 14. Trade-offs

| Choice | Upside | Downside |
|--------|--------|----------|
| Sync `/run` | Simple | Long HTTP requests; needs ≥120s timeouts |
| SERP proxy for “AI visibility” | Real, measurable | Not ChatGPT/Claude citation truth |
| Manual validation | Fewer dependencies | Less schema automation than Pydantic |
| Standard Python logging | Simple | No structured logs / correlation IDs |
| Soft Agent 3 / all-Agent-2-fail → `completed` | Preserves useful discovered/scored data | Clients must read `error_message` |
| SQLite | Easy local/Docker start | Weaker under concurrent writers |

---

## 15. Limitations

Intentionally **not** implemented (assessment out of scope or bonus not taken):

- Authentication / authorization
- Async pipeline execution
- Status polling endpoint
- Rate limiting on `/run`
- Structured logging with correlation IDs per pipeline run
- Pydantic or Marshmallow request/response schemas
- Frontend UI
- True generative-engine citation tracking (SERP proxy only)

Other practical limits: DataForSEO/LLM cost and rate limits; recheck re-estimates commercial intent (no dedicated intent column).

---

## 16. AI Coding Tools

- **Cursor** (Composer) assisted scaffolding, iterative implementation, tests, Docker, and documentation drafts.
- Implementation decisions, architecture review, formula design, failure semantics, and verification remained under developer control.
- This README documents only features that exist in the repository.

---

## 17. Assessment Compliance Checklist

### Required

- [x] Flask `create_app()` factory
- [x] Blueprints and `/api/v1` routes
- [x] SQLAlchemy models
- [x] Migrations (Flask-Migrate / Alembic)
- [x] UUID primary keys and required model fields
- [x] Six REST endpoints
- [x] Three AI agents with separated responsibilities
- [x] Pipeline orchestrator (Agent 1 → 2 → 3)
- [x] Prompt engineering + structured JSON output
- [x] JSON validation and malformed-LLM recovery
- [x] Consistent HTTP error handling
- [x] Environment config + `.env.example`
- [x] DataForSEO integration (real volume / competition / SERP visibility)
- [x] OpenAI and/or Anthropic support
- [x] Opportunity score (0–1) documented
- [x] Runnable app (local + Docker Compose)
- [x] Unit tests for agent logic (mocked LLM)
- [x] README covering setup, architecture, agents, formula, tradeoffs

### Bonus features (accurate status)

**Implemented**

- Unit tests for agent logic using mocked LLM responses
- Docker Compose setup

**Not implemented**

- Async pipeline execution with status polling endpoint
- Rate limiting on the pipeline trigger endpoint
- Request/response validation using Pydantic or Marshmallow
- Structured logging with correlation IDs per pipeline run

---

## 18. Folder Structure

```
app/
  __init__.py              # create_app()
  config.py / extensions.py
  api/                     # blueprints, validators, serializers, errors
  agents/                  # discovery, scoring, recommendation, prompts, types
  models/                  # BusinessProfile, PipelineRun, DiscoveredQuery, ContentRecommendation
  services/                # orchestrator, persistence, LLM, DataForSEO, query service
  utils/                   # scoring, JSON parser, domains, datetime
migrations/
tests/
scripts/docker-entrypoint.sh
wsgi.py
Dockerfile
docker-compose.yml
requirements.txt
.env.example
README.md
pytest.ini
```

---

## Example end-to-end flow

```text
POST /api/v1/profiles
POST /api/v1/profiles/{uuid}/run
GET  /api/v1/profiles/{uuid}/queries?min_score=0.7&status=not_visible
GET  /api/v1/profiles/{uuid}/recommendations
POST /api/v1/queries/{query_uuid}/recheck
```
