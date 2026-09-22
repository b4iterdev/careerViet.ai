# careerViet.ai

Local-first CLI for job import, evidence-grounded profiles and evaluations, reviewed CV PDF export, and local application drafts.

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

## Milestone 4: Reviewed CVs and Local Application Drafts

M4 adds immutable SQLite CV revisions and explicit hash-bound approval, EN/VI PDF export,
CLI-agent/direct-provider tailoring proposals, and local email/form drafts. No applications
are sent. Every generated document remains separate from the application tracker.

### Create, review, approve, export

Use a **confirmed** profile version and its actual evidence IDs (shown by the profile workflow).
Replace the uppercase placeholders below. Repeat `--evidence` to select multiple items.
Omit `--job-id` for a general CV; add it to bind the CV to a stored job.

```bash
uv run careerviet --workspace data cv create --profile-version VERSION --evidence EVIDENCE_ID --language vi --identity name
uv run careerviet --workspace data cv list
uv run careerviet --workspace data cv review CV_ID
uv run careerviet --workspace data cv approve CV_ID --hash EXACT_REVIEW_HASH
uv run careerviet --workspace data cv export CV_ID --output /tmp/new-cv-bundle --max-pages 2
```

Export contains `cv.pdf` and `cv.json`. Output directories must not already exist, and their
parent must exist. The renderer fails rather than silently shortening content to meet the page
budget. `--max-pages` supports 1–10, default 2. The single-column A4 layout uses bundled,
embedded Noto Sans with Vietnamese glyphs. Unsupported glyphs fail clearly. It uses ReportLab
rather than requiring a separate Typst compiler; all candidate strings are escaped data.
No universal ATS compatibility claim is made.

**Language and truthfulness:** `en`/`vi` chooses headings; extractive creation preserves original
evidence wording and does not pretend to translate it. For translation/tailoring, export a packet
for a CLI agent or use an explicitly consented provider. Every rewrite is an unapproved proposal.
Exact quote validation proves provenance, **not semantic truth** or relevance. The candidate must
review dates, employment/volunteer distinctions, qualifications, metrics and uncertainty before
approving the exact content hash. Local identity fields are opt-in via repeated `--identity`.
There is no mandatory photo, DOB, marital status, GitHub or technical-project section.

### Tailoring and translations

```bash
uv run careerviet --workspace data cv export-packet CV_ID --output /tmp/new-tailoring-packet --consent
uv run careerviet --workspace data cv import-response CV_ID --response response.json
uv run careerviet cv skill
```

The packet contains strict instructions, selected claims, target language, optional JD and a
canonical hash. A response has only `packet_hash` and `claims`; keep evidence IDs in order and
preserve exact quote/status/uncertainty. Set `mode` to `proposed` when changing text. Import creates
a **new unapproved revision**. For manual edits, `cv revise CV_ID --claims claims.json` accepts
an array of the same claim objects. Re-review and approve the new ID, never the old hash.

Direct-provider mode uses `CAREERVIET_EVAL_ENDPOINT` (complete chat/completions endpoint),
`CAREERVIET_EVAL_MODEL`, and `CAREERVIET_EVAL_API_KEY` from your securely configured environment:

```bash
uv run careerviet --workspace data cv provider CV_ID --consent
```

Configure and inspect the destination/model before consenting. Selected evidence/JD leaves the
device; separate profile identity fields are omitted, **but personal details embedded in quotes
are not automatically scrubbed**. Review those before export/transmission. Provider output uses
the same canonical import checks and remains unapproved. HTTPS required; loopback HTTP requires
`CAREERVIET_EVAL_ALLOW_LOOPBACK_HTTP=1` for local testing. Requests do not follow redirects and
response bytes/time are bounded. No live production provider has been verified for M4; tests
cover synthetic mocks and a real loopback HTTP server.

### Local email/form drafts

Subject and application route must be supplied exactly by the user/from the employer's instructions.
The selected approved CV controls language and candidate wording. Drafts do not attach a CV or send anything.

```bash
uv run careerviet --workspace data draft create CV_ID --job-id JOB_ID --subject 'EXACT SUBJECT' --route 'EXACT APPLICATION ROUTE' --questions questions.json
uv run careerviet --workspace data draft review DRAFT_ID
uv run careerviet --workspace data draft approve DRAFT_ID --hash EXACT_REVIEW_HASH
uv run careerviet --workspace data draft export DRAFT_ID --output /tmp/new-application-bundle
```

`--questions` is optional. Its format is:

```json
{"questions": ["Relevant experience?", "Available start date?"], "answers": {"0": "EVIDENCE_ID"}}
```

Answer keys are zero-based question indexes; values select approved CV evidence text. Unknown
answers remain `[UNANSWERED]`, not inferred. Quote existence does not prove question relevance;
review that explicitly. To change answers/subject/route create another immutable draft. Freeform
answer composition is deliberately limited to reviewed CV wording; revise the CV first if needed.
Exports contain `email.txt`, `form.txt`, `application.json`, and `README.txt` with route/warnings.
Profile/CV/JD hashes persist with each draft; stale canonical inputs block approval/export.

### Reproducible synthetic smoke

```bash
uv run pytest -q
uv run ruff check .
uv run python scripts/run_m4_smoke.py
uv build
```

The smoke uses only a new OS temporary workspace and prints its retained EN/VI PDF, preview image
and application bundle locations. It exercises separate real CLI processes, text extraction,
page count, text bounding boxes, unanswered questions and the unchanged `applied` flag.
Synthetic examples are demonstrations, not real candidates or job opportunities.

## Milestone 5: Local Application Tracking

Tracking is explicit and independent of document generation. `apply` **records an already
manually submitted application; it does not send anything**. Commands below return JSON.

```bash
uv run careerviet --workspace data track JOB_ID
uv run careerviet --workspace data track JOB_ID --state shortlisted
uv run careerviet --workspace data track JOB_ID --state drafting
uv run careerviet --workspace data track JOB_ID --state ready --cv APPROVED_CV_ID
# Only after you have manually submitted that CV:
uv run careerviet --workspace data apply JOB_ID --cv APPROVED_CV_ID --confirm
uv run careerviet --workspace data track JOB_ID --state interviewing
uv run careerviet --workspace data applications list --state interviewing
uv run careerviet --workspace data applications history JOB_ID
uv run careerviet applications skill
```

Allowed transitions:

| From | To |
|---|---|
| discovered | shortlisted, archived |
| shortlisted | drafting, withdrawn, archived |
| drafting | ready, shortlisted, withdrawn, archived |
| ready | drafting, applied, withdrawn, archived |
| applied | interviewing, offer, rejected, withdrawn, archived |
| interviewing | offer, rejected, withdrawn, archived |
| offer | withdrawn, archived |
| rejected / withdrawn | archived |
| archived | terminal |

Ready requires a current approved CV for this job (or an untargeted CV). To replace a ready CV,
return to drafting first. Applied requires the same reviewed selection, unchanged JD, and explicit
confirmation. Snapshots retain CV revision/hash, profile version and exact JD content. The UTC
`applied_at` records when confirmation was entered, not independently verified submission time.
Later outcomes preserve it; `jobs.applied` means ever confirmed applied. History starts with the
first explicit transition; import's discovered state is the initial baseline. No automatic reopen
or multiple submission attempts per job in M5.

State, event and applied-flag writes are transactional. Existing application rows are reused;
ambiguous duplicate legacy rows fail closed without silently deleting records. Snapshot hashes
catch accidental payload changes, not a malicious local actor rewriting both content and hash.
Snapshots remain readable after live JD changes. Database migration adds tracking columns/tables
on first tracking use; back up private workspaces before upgrading.

URL checks reject nonpublic DNS answers (including shared address space) and revalidate redirects.
They do **not** pin DNS answers to the socket: DNS-rebinding protection is not claimed. Existing
host allowlists and source restrictions remain; no arbitrary URL ingestion was introduced.

Run the synthetic, separate-process tracking smoke with `uv run python scripts/run_m5_smoke.py`.

## Current Scope

Milestones 1 through 5 implement:
1. Local manual text/file JD import, Pydantic contracts, SQLite persistence with provenance, and stable dedupe.
2. Bounded public HTTP ingestion for ITviec and VietnamWorks with robots/terms checks and offline fixture modes.
3. Conversational candidate onboarding, versioned profiles, deterministic triage, and privacy-grounded dual-runtime JD evaluation contracts.
4. Reviewed CV PDF/JSON bundles, tailoring proposals, and local email/form application drafts.
5. Explicit local application states, confirmation gates, version snapshots and transition history.

Imported jobs are never automatically marked applied or submitted externally.

## Limitations

Sending, web dashboard, legal calculations and additional source coverage
remain deferred. The local workspace database is not encrypted at rest; protect its directory
and backups. Existing ingestion restrictions remain. Automatic translation is not part of the
extractive path, and generative factual correctness always requires human review.
