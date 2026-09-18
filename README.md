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

## Current Scope

Milestone 1 implements only local manual text/file JD import, Pydantic contracts, SQLite persistence with provenance, internal dedupe, and CLI inspection commands. Imported jobs are stored as `discovered` and are never marked applied.

JD deduplication uses a normalized content hash that is independent of the source path or paste identity. Normalization trims surrounding whitespace and ignores trailing spaces at line ends; it does not rewrite punctuation, casing, accents, Unicode forms, wording, line order, or semantically equivalent ads. Each import attempt is retained as a local source observation with its source identity, timestamp, and raw text.

## Limitations

Manual JD parsing is label-based and conservative. It recognizes common Vietnamese labels such as `Tiêu đề`, `Công ty`, `Địa điểm`, `Mô tả công việc`, `Yêu cầu công việc`, `Quyền lợi`, and `Lương`; unrecognized prose is retained as unparsed freeform text rather than treated as reliably extracted facts. Salary parsing distinguishes unknown, hidden, negotiable, and explicit zero salary, but it does not infer ambiguous amounts, currency, period, or gross/net status.

No LLM/provider calls, CV rendering, application drafting, application sending, tax calculations, credentials, browser automation, CAPTCHA/WAF bypass, or external submissions are implemented. Manual import remains available as the fallback when HTTP sources are blocked, unverified, unsupported, or schema-changed.
