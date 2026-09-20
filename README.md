# careerViet.ai

Local-first CLI foundation for milestone 1: manual job-description import, stable deduplication, SQLite persistence, and inspectable Typer commands.

## Setup

```bash
uv sync
```

## Tests

```bash
uv run pytest tests/unit/test_models.py -q
uv run pytest tests/unit/test_manual_import.py -q
uv run pytest tests/integration/test_cli.py -q
uv run pytest -q
uv run ruff check .
```

## HTTP Source Ingestion

Milestone 2 adds bounded, opt-in public HTTP ingestion for the observed ITviec and VietnamWorks sources while preserving manual import and SQLite behavior. Offline fixture mode is the default for HTTP source commands; live public HTTP requires `--live`.

Search an offline ITviec fixture without importing:

```bash
uv run careerviet --workspace /tmp/careerviet-fixture jobs search --source itviec --fixture tests/fixtures/http/itviec_search.html --keyword C++
```

Import matching offline fixture jobs:

```bash
uv run careerviet --workspace /tmp/careerviet-fixture jobs ingest --source itviec --fixture tests/fixtures/http/itviec_search.html --keyword C++
```

Live use is conservative and bounded. Unknown policy, access restrictions, schema drift, missing VietnamWorks payload provenance, challenges, 403, and 429 responses are reported as structured states rather than treated as empty success. The VietnamWorks adapter supports offline parsing of observed JSON shapes but live POST search remains unsupported until request payload provenance is available.

Run the bounded live benchmark:

```bash
uv run python scripts/run_milestone2_benchmark.py --output docs/benchmarks/milestone-2-live-benchmark.json
```

The benchmark is limited to 12 total public HTTPS requests and records actual status, bytes, latency, policy state, and extraction counts under `docs/benchmarks/`.

## CLI Smoke Usage

Initialize a workspace:

```bash
uv run careerviet --workspace data init
```

Import the same JD twice to verify stable dedupe:

```bash
uv run careerviet --workspace data import-jd --file tests/fixtures/synthetic_jd.txt
uv run careerviet --workspace data import-jd --file tests/fixtures/synthetic_jd.txt
```

Paste a JD from standard input instead of reading a file:

```bash
uv run careerviet --workspace data import-jd --stdin < tests/fixtures/synthetic_customer_jd.txt
```

`--file` and `--stdin` are mutually exclusive.

List and show persisted jobs:

```bash
uv run careerviet --workspace data jobs list
uv run careerviet --workspace data jobs show <job_id>
```

Check profile validation and local health:

```bash
uv run careerviet --workspace data profile validation
uv run careerviet --workspace data doctor
```

## Milestone 3: Profile Onboarding & Grounded Evaluation

Milestone 3 implements conversational profile onboarding, immutable evidence profiles, deterministic constraint triage, and dual-runtime evaluation contracts (CLI agent packet export/import and direct OpenAI-compatible provider evaluation).

### Conversational Onboarding CLI

Start or resume onboarding questions one at a time:

```bash
uv run careerviet --workspace data profile answer --draft-id draft-1 --text "Synthetic candidate, contact private, based in Ha Noi."
```

Review draft status and correct specific fields:

```bash
uv run careerviet --workspace data profile review --draft-id draft-1
uv run careerviet --workspace data profile correct --draft-id draft-1 --field preferences --text "Preferences: Ha Noi, remote yes."
```

Explicitly confirm draft to store an immutable versioned profile:

```bash
uv run careerviet --workspace data profile confirm --draft-id draft-1
```

### Deterministic Constraint Triage

Check hard constraints (location, compensation floors, engagement type) before spending model evaluation:

```bash
uv run careerviet --workspace data evaluate triage <job_id>
```

### Dual-Runtime Evaluation

Export privacy-redacted evaluation packet (omits candidate identity, binds canonical hashes, requires `--consent`):

```bash
uv run careerviet --workspace data evaluate export-packet <job_id> --profile-version <version> --output packet.json --consent
```

Import and validate candidate-grounded evaluation report:

```bash
uv run careerviet --workspace data evaluate import-report --packet packet.json --response report.json
```

Direct OpenAI-compatible evaluation is also available programmatically via `run_direct_provider_evaluation` with `EvaluationProviderConfig.from_env()`.

## Current Scope

Milestones 1 through 3 implement:
1. Local manual text/file JD import, Pydantic contracts, SQLite persistence with provenance, and stable dedupe.
2. Bounded public HTTP ingestion for ITviec and VietnamWorks with robots/terms checks and offline fixture modes.
3. Conversational candidate onboarding, versioned profiles, deterministic triage, and privacy-grounded dual-runtime JD evaluation contracts.

Imported jobs remain in discovered/evaluated state and are never automatically marked applied or submitted externally.

## Limitations

No CV rendering, application drafting/sending, mass scraping, or automatic submissions are implemented in milestone 3. Live direct-provider calls require explicit user consent and secure environment configuration.
