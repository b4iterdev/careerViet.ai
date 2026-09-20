# pyright: reportMissingTypeStubs=false
from pathlib import Path

import pytest

from careerviet.onboarding import OnboardingAnswer, ProfileOnboarding
from careerviet.storage.repository import CareerRepository


def test_onboarding_resumes_review_corrects_and_confirms_immutable_profile(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()

    session = ProfileOnboarding.start(repository, draft_id="draft-synthetic")
    assert session.next_question().field == "identity"
    session.answer(
        OnboardingAnswer(
            text="Synthetic candidate Linh, contact private, based in Ha Noi.",
            answered_by="synthetic_fixture",
        )
    )
    session.answer(
        OnboardingAnswer(
            text="Targets: retail cashier first, warehouse associate second.",
            answered_by="synthetic_fixture",
        )
    )
    session.answer(
        OnboardingAnswer(
            text="Experience: cashier 2022-01 to 2024-06 full-time; volunteered at a food bank.",
            answered_by="synthetic_fixture",
        )
    )
    session.answer(OnboardingAnswer(text="Education: high school diploma.", answered_by="synthetic_fixture"))
    session.answer(
        OnboardingAnswer(
            text="License: forklift safety certificate expires 2027-05-01.",
            answered_by="synthetic_fixture",
        )
    )

    resumed = ProfileOnboarding.resume(repository, draft_id="draft-synthetic")
    assert resumed.next_question().field == "skills_languages"
    resumed.answer(
        OnboardingAnswer(
            text="Skills: POS, inventory; Languages: Vietnamese native, English basic.",
            answered_by="synthetic_fixture",
        )
    )
    resumed.answer(
        OnboardingAnswer(
            text="Preferences: Ha Noi, remote no, shifts day, no travel, exclude tobacco industry.",
            answered_by="synthetic_fixture",
        )
    )
    resumed.answer(
        OnboardingAnswer(
            text="Compensation: full-time floor 9000000 VND/month gross; internship floor unknown.",
            answered_by="synthetic_fixture",
        )
    )
    resumed.answer(
        OnboardingAnswer(
            text="Availability: current immediate for full-time; future internship unavailable.",
            answered_by="synthetic_fixture",
        )
    )

    review = resumed.review()
    assert review.status == "ready_for_confirmation"
    assert review.draft_only is True
    assert "full-time floor 9000000 VND/month gross" in review.summary

    resumed.correct(
        field="preferences",
        answer=OnboardingAnswer(
            text="Preferences: Ha Noi or Bac Ninh, remote no, shifts day, no travel, exclude tobacco industry.",
            answered_by="synthetic_fixture",
        ),
    )
    profile = resumed.confirm(confirmed_by="synthetic_fixture")

    assert profile.profile_id.startswith("profile_")
    assert profile.version.startswith("v")
    assert profile.confirmed_at is not None
    assert profile.preferences.full_time_compensation_floor is not None
    assert profile.preferences.full_time_compensation_floor.amount == 9_000_000
    assert "Bac Ninh" in profile.preferences.preferred_locations
    assert {target.occupation_family for target in profile.ranked_targets} == {"retail", "logistics"}
    assert any(experience.engagement_type == "volunteer" for experience in profile.experience)
    assert len({evidence.evidence_id for evidence in profile.evidence}) == len(profile.evidence)

    with pytest.raises(ValueError, match="immutable"):
        repository.save_confirmed_profile(profile)


def test_profile_rejects_duplicate_evidence_ids() -> None:
    payload = {
        "profile_id": "profile_duplicate",
        "version": "v20260919T000000Z-a",
        "evidence": [
            {
                "evidence_id": "ev_identity_001",
                "status": "candidate_confirmed",
                "summary": "Synthetic identity statement.",
                "source": "synthetic_fixture",
                "source_quote": "Synthetic identity statement.",
                "provenance": "profile_onboarding",
                "uncertainty": "low",
            },
            {
                "evidence_id": "ev_identity_001",
                "status": "candidate_confirmed",
                "summary": "Duplicate synthetic identity statement.",
                "source": "synthetic_fixture",
                "source_quote": "Duplicate synthetic identity statement.",
                "provenance": "profile_onboarding",
                "uncertainty": "low",
            },
        ],
    }

    with pytest.raises(ValueError, match="duplicate evidence ids"):
        ProfileOnboarding.profile_model().model_validate(payload)
