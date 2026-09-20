# pyright: reportMissingTypeStubs=false
from datetime import UTC, datetime

import httpx
import pytest

from careerviet.evaluation_runtime import (
    EvaluationProviderConfig,
    create_evaluation_packet,
    run_direct_provider_evaluation,
    validate_evaluation_response,
)
from careerviet.models.job import EmploymentType, Job, Salary, SalaryKind, SourceProvenance
from careerviet.models.profile import CandidateEvidence, CandidateProfile, EvidenceStatus
from careerviet.storage.repository import CareerRepository


def _profile() -> CandidateProfile:
    return CandidateProfile(
        profile_id="profile_packet",
        version="v20260919T020000Z-packet",
        confirmed_at=datetime(2026, 9, 19, tzinfo=UTC),
        identity={"summary": "Synthetic candidate, contact private"},
        evidence=[
            CandidateEvidence(
                evidence_id="ev_python",
                status=EvidenceStatus.CANDIDATE_CONFIRMED,
                summary="Built Python inventory scripts.",
                source="synthetic_fixture",
                source_quote="Built Python inventory scripts.",
                provenance="experience",
                uncertainty="low",
            ),
            CandidateEvidence(
                evidence_id="ev_cashier",
                status=EvidenceStatus.CANDIDATE_CONFIRMED,
                summary="Worked as a cashier.",
                source="synthetic_fixture",
                source_quote="Worked as a cashier.",
                provenance="experience",
                uncertainty="low",
            ),
        ],
    )


def _job() -> Job:
    return Job(
        job_id="job_packet",
        content_hash="c" * 64,
        source=SourceProvenance(
            source_id="manual:packet",
            source_kind="manual_text",
            original_uri="synthetic",
            retrieved_at=datetime(2026, 9, 19, tzinfo=UTC),
        ),
        title="Python Inventory Assistant",
        employer="Synthetic Warehouse",
        location="Ha Noi",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.UNKNOWN),
        description="Maintain inventory tools.",
        requirements="Python inventory scripting\nWarehouse operations",
    )


def test_packet_export_requires_consent_omits_identity_and_binds_hashes(tmp_path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    profile = _profile()
    job = _job()
    repository.save_confirmed_profile(profile)
    repository.upsert_job(job, source_identity="synthetic", raw_content="Python inventory scripting")

    with pytest.raises(PermissionError, match="export consent"):
        create_evaluation_packet(repository, profile.version, job.job_id or "", export_consent=False)

    packet = create_evaluation_packet(repository, profile.version, job.job_id or "", export_consent=True)

    dumped = packet.model_dump_json()
    assert "Synthetic candidate" not in dumped
    assert packet.profile_version == profile.version
    assert packet.jd_content_hash == job.content_hash
    assert [requirement.requirement_id for requirement in packet.requirements] == ["req_001", "req_002"]


def test_response_validation_rejects_spoofed_stale_duplicate_and_unrelated_support(tmp_path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    profile = _profile()
    job = _job()
    repository.save_confirmed_profile(profile)
    repository.upsert_job(job, source_identity="synthetic", raw_content="Python inventory scripting")
    packet = create_evaluation_packet(repository, profile.version, job.job_id or "", export_consent=True)

    valid_response = {
        "packet_id": packet.packet_id,
        "profile_version": profile.version,
        "job_id": job.job_id,
        "jd_content_hash": job.content_hash,
        "model": "mock-model",
        "runtime": "mock-runtime",
        "verdict": "practical_fit",
        "confidence": "medium",
        "requirement_judgments": [
            {
                "requirement_id": "req_001",
                "status": "supported",
                "evidence_ids": ["ev_python"],
                "source_quotes": ["Built Python inventory scripts."],
                "gaps": [],
                "questions": [],
            },
            {
                "requirement_id": "req_002",
                "status": "human_review",
                "evidence_ids": [],
                "source_quotes": [],
                "gaps": ["Warehouse operations not mechanically verified."],
                "questions": ["Confirm warehouse operations depth."],
            },
        ],
    }
    report = validate_evaluation_response(repository, packet, valid_response)
    assert report.verdict == "practical_fit"

    unrelated = valid_response | {
        "requirement_judgments": [
            valid_response["requirement_judgments"][0] | {
                "evidence_ids": ["ev_cashier"],
                "source_quotes": ["Worked as a cashier."],
            },
            valid_response["requirement_judgments"][1],
        ]
    }
    with pytest.raises(ValueError, match="unsupported factual mapping"):
        validate_evaluation_response(repository, packet, unrelated)

    stale = valid_response | {"jd_content_hash": "d" * 64}
    with pytest.raises(ValueError, match="canonical job content"):
        validate_evaluation_response(repository, packet, stale)


def test_provider_requires_consent_secure_config_and_does_not_persist_failure(tmp_path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    profile = _profile()
    job = _job()
    repository.save_confirmed_profile(profile)
    repository.upsert_job(job, source_identity="synthetic", raw_content="Python inventory scripting")
    packet = create_evaluation_packet(repository, profile.version, job.job_id or "", export_consent=True)

    config = EvaluationProviderConfig.from_env(
        {
            "CAREERVIET_EVAL_ENDPOINT": "http://127.0.0.1:9999/v1/chat/completions",
            "CAREERVIET_EVAL_MODEL": "mock-model",
            "CAREERVIET_EVAL_API_KEY": "secret-test-key",
            "CAREERVIET_EVAL_ALLOW_LOOPBACK_HTTP": "1",
        }
    )
    with pytest.raises(PermissionError, match="explicit provider consent"):
        run_direct_provider_evaluation(repository, packet, config, provider_consent=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-test-key"
        return httpx.Response(401, json={"error": "secret-test-key should not leak"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(RuntimeError, match="provider request failed with status 401") as exc_info:
        run_direct_provider_evaluation(
            repository,
            packet,
            config,
            provider_consent=True,
            transport=transport,
        )

    assert "secret-test-key" not in str(exc_info.value)
    assert repository.count_evaluation_reports() == 0


def test_provider_success_roundtrip_persists_report(tmp_path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    profile = _profile()
    job = _job()
    repository.save_confirmed_profile(profile)
    repository.upsert_job(job, source_identity="synthetic", raw_content="Python inventory scripting")
    packet = create_evaluation_packet(repository, profile.version, job.job_id or "", export_consent=True)

    config = EvaluationProviderConfig.from_env(
        {
            "CAREERVIET_EVAL_ENDPOINT": "http://127.0.0.1:9999/v1/chat/completions",
            "CAREERVIET_EVAL_MODEL": "mock-model",
            "CAREERVIET_EVAL_API_KEY": "secret-test-key",
            "CAREERVIET_EVAL_ALLOW_LOOPBACK_HTTP": "1",
        }
    )

    valid_response_json = {
        "packet_id": packet.packet_id,
        "profile_version": packet.profile_version,
        "job_id": packet.job_id,
        "jd_content_hash": packet.jd_content_hash,
        "model": "mock-model",
        "runtime": "direct_provider",
        "verdict": "practical_fit",
        "confidence": "high",
        "requirement_judgments": [
            {
                "requirement_id": "req_001",
                "status": "supported",
                "evidence_ids": ["ev_python"],
                "source_quotes": ["Built Python inventory scripts."],
                "gaps": [],
                "questions": [],
            },
            {
                "requirement_id": "req_002",
                "status": "human_review",
                "evidence_ids": [],
                "source_quotes": [],
                "gaps": ["Warehouse operations not verified."],
                "questions": ["Confirm warehouse depth."],
            },
        ],
    }

    import json

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-test-key"
        mock_body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(valid_response_json),
                    }
                }
            ]
        }
        return httpx.Response(200, json=mock_body)

    transport = httpx.MockTransport(handler)
    report = run_direct_provider_evaluation(
        repository,
        packet,
        config,
        provider_consent=True,
        transport=transport,
    )
    assert report.verdict == "practical_fit"
    assert repository.count_evaluation_reports() == 1
