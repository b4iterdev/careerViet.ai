"""Tests for Claim section and mode alias normalization."""

from mocnghe.cv import Claim


def test_claim_normalizes_section_aliases():
    c1 = Claim.model_validate({
        "evidence_id": "ev1",
        "source_quote": "Quote 1",
        "text": "Quote 1",
        "section": "summary",
        "uncertainty": "low",
        "status": "candidate_confirmed",
    })
    assert c1.section == "other"

    c2 = Claim.model_validate({
        "evidence_id": "ev1",
        "source_quote": "Quote 1",
        "text": "Quote 1",
        "section": "projects",
        "uncertainty": "low",
        "status": "candidate_confirmed",
    })
    assert c2.section == "other"

    c3 = Claim.model_validate({
        "evidence_id": "ev1",
        "source_quote": "Quote 1",
        "text": "Quote 1",
        "section": "certifications",
        "uncertainty": "low",
        "status": "candidate_confirmed",
    })
    assert c3.section == "credentials"


def test_claim_normalizes_mode_aliases():
    c = Claim.model_validate({
        "evidence_id": "ev1",
        "source_quote": "Quote 1",
        "text": "Tailored quote",
        "section": "skills",
        "mode": "rewrite",
        "uncertainty": "low",
        "status": "candidate_confirmed",
    })
    assert c.mode == "proposed"
