"""End-to-end agent skill roundtrip:
  profile confirm-file → JD import → evaluate export-packet
  → synthetic agent response → evaluate import-report.

Simulates the full agent-as-reviewer path without a real provider.
"""

import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from mocnghe.cli import app
from mocnghe.models.profile import CandidateEvidence, CandidateProfile, EvidenceStatus
from mocnghe.storage.repository import CareerRepository

# ── synthetic fixtures ────────────────────────────────────────────────────────

_PROFILE = CandidateProfile(
    profile_id="roundtrip_candidate",
    version="v1",
    confirmed_at=datetime.now(UTC),
    identity={"name": "Roundtrip User"},
    evidence=[
        CandidateEvidence(
            evidence_id="ev_python",
            status=EvidenceStatus.DOCUMENT_VERIFIED,
            summary="Built Python inventory scripts.",
            source="synthetic_cv",
            source_quote="Built Python inventory scripts.",
            provenance="experience",
            uncertainty="low",
        ),
        CandidateEvidence(
            evidence_id="ev_sql",
            status=EvidenceStatus.DOCUMENT_VERIFIED,
            summary="Used PostgreSQL database for persistent storage.",
            source="synthetic_cv",
            source_quote="Used PostgreSQL database for persistent storage.",
            provenance="experience",
            uncertainty="low",
        ),
    ],
)

_JD_TEXT = """\
Title: Backend Developer Intern
Company: Synthetic Corp

Required Qualifications:
- Python or similar scripting language
- Basic SQL / database experience

Good to Have:
- Docker experience
"""


def _run(runner, workspace, *args, input=None):
    return runner.invoke(app, ["--workspace", str(workspace), *args], input=input)


def test_eval_agent_roundtrip(tmp_path):
    """Full path: profile → JD → export-packet → synthetic response → import-report."""
    ws = tmp_path / "ws"
    runner = CliRunner()

    # Init workspace and save confirmed profile
    _run(runner, ws, "init")
    repo = CareerRepository(ws)
    repo.initialize()
    repo.save_confirmed_profile(_PROFILE)

    # Import JD
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text(_JD_TEXT)
    result = _run(runner, ws, "import-jd", "--file", str(jd_file))
    assert result.exit_code == 0, result.output
    job_id = result.stdout.split()[1]

    # Export eval packet
    packet_file = tmp_path / "packet.json"
    result = _run(runner, ws, "evaluate", "export-packet", job_id,
                  "--profile-version", "v1", "--output", str(packet_file), "--consent")
    assert result.exit_code == 0, result.output + str(result.exception)
    packet = json.loads(packet_file.read_text())

    # Verify packet has structured requirements (not just "unknown")
    assert len(packet["requirements"]) >= 2
    req_texts = [r["text"] for r in packet["requirements"]]
    assert any("Python" in t for t in req_texts)
    assert any("SQL" in t or "database" in t.lower() for t in req_texts)
    req_ids = [r["requirement_id"] for r in packet["requirements"]]
    assert req_ids == sorted(req_ids)  # sequential

    # Packet has selected evidence (identity excluded)
    ev_ids = [e["evidence_id"] for e in packet["selected_evidence"]]
    assert "ev_python" in ev_ids
    assert "ev_sql" in ev_ids

    # Simulate agent: build a valid response matching all requirement_ids
    req_judgments = []
    for req in packet["requirements"]:
        if "Python" in req["text"]:
            req_judgments.append({
                "requirement_id": req["requirement_id"],
                "status": "supported",
                "evidence_ids": ["ev_python"],
                "source_quotes": ["Built Python inventory scripts."],
                "gaps": [],
                "questions": [],
            })
        elif "SQL" in req["text"] or "database" in req["text"].lower():
            req_judgments.append({
                "requirement_id": req["requirement_id"],
                "status": "supported",
                "evidence_ids": ["ev_sql"],
                "source_quotes": ["Used PostgreSQL database for persistent storage."],
                "gaps": [],
                "questions": [],
            })
        else:
            req_judgments.append({
                "requirement_id": req["requirement_id"],
                "status": "human_review",
                "evidence_ids": [],
                "source_quotes": [],
                "gaps": ["Not evidenced."],
                "questions": [],
            })

    response_payload = {
        "packet_id": packet["packet_id"],
        "profile_version": packet["profile_version"],
        "job_id": packet["job_id"],
        "jd_content_hash": packet["jd_content_hash"],
        "model": "synthetic-agent-v1",
        "runtime": "synthetic",
        "verdict": "practical_fit",
        "confidence": "medium",
        "requirement_judgments": req_judgments,
    }
    response_file = tmp_path / "response.json"
    response_file.write_text(json.dumps(response_payload))

    # Import report
    result = _run(runner, ws, "evaluate", "import-report",
                  "--packet", str(packet_file), "--response", str(response_file))
    assert result.exit_code == 0, result.output + str(result.exception)
    assert "stored report" in result.stdout


def test_eval_agent_roundtrip_rejects_mismatched_packet_id(tmp_path):
    """import-report rejects a response with wrong packet_id."""
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")
    repo = CareerRepository(ws)
    repo.initialize()
    repo.save_confirmed_profile(_PROFILE)

    jd_file = tmp_path / "jd.txt"
    jd_file.write_text(_JD_TEXT)
    result = _run(runner, ws, "import-jd", "--file", str(jd_file))
    job_id = result.stdout.split()[1]

    packet_file = tmp_path / "packet.json"
    _run(runner, ws, "evaluate", "export-packet", job_id,
         "--profile-version", "v1", "--output", str(packet_file), "--consent")
    packet = json.loads(packet_file.read_text())

    bad_response = {
        "packet_id": "packet_" + "deadbeef" * 2,  # wrong id
        "profile_version": packet["profile_version"],
        "job_id": packet["job_id"],
        "jd_content_hash": packet["jd_content_hash"],
        "model": "x", "runtime": "x",
        "verdict": "not_fit", "confidence": "low",
        "requirement_judgments": [
            {"requirement_id": r["requirement_id"], "status": "gap",
             "evidence_ids": [], "source_quotes": [], "gaps": [], "questions": []}
            for r in packet["requirements"]
        ],
    }
    response_file = tmp_path / "response.json"
    response_file.write_text(json.dumps(bad_response))
    result = _run(runner, ws, "evaluate", "import-report",
                  "--packet", str(packet_file), "--response", str(response_file))
    assert result.exit_code != 0


def test_eval_packet_omits_identity_evidence(tmp_path):
    """export-packet must not include evidence tagged provenance=identity."""
    profile_with_identity_ev = _PROFILE.model_copy(update={
        "evidence": [
            *_PROFILE.evidence,
            CandidateEvidence(
                evidence_id="ev_identity_phone",
                status="candidate_confirmed",
                summary="Phone: 099-xxx-xxxx",
                source="synthetic",
                provenance="identity",
                uncertainty="low",
            ),
        ]
    })
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")
    repo = CareerRepository(ws)
    repo.initialize()
    repo.save_confirmed_profile(profile_with_identity_ev)

    jd_file = tmp_path / "jd.txt"
    jd_file.write_text(_JD_TEXT)
    result = _run(runner, ws, "import-jd", "--file", str(jd_file))
    job_id = result.stdout.split()[1]

    packet_file = tmp_path / "packet.json"
    _run(runner, ws, "evaluate", "export-packet", job_id,
         "--profile-version", "v1", "--output", str(packet_file), "--consent")
    packet = json.loads(packet_file.read_text())

    ev_ids = [e["evidence_id"] for e in packet["selected_evidence"]]
    assert "ev_identity_phone" not in ev_ids
    assert "ev_python" in ev_ids
