import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from .models.profile import (
    CandidateEvidence,
    CandidateProfile,
    CompensationFloor,
    EvidenceStatus,
    ProfileCredential,
    ProfileExperience,
    RankedTarget,
    WorkPreferences,
)
from .storage.repository import CareerRepository


class OnboardingAnswer(BaseModel):
    text: str = Field(min_length=1)
    answered_by: str = Field(min_length=1)


class OnboardingQuestion(BaseModel):
    field: str
    prompt: str


class OnboardingReview(BaseModel):
    status: Literal["incomplete", "ready_for_confirmation"]
    draft_only: bool
    summary: str
    missing_fields: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _FieldSpec:
    field: str
    prompt: str


class ProfileOnboarding:
    _FIELDS: ClassVar[tuple[_FieldSpec, ...]] = (
        _FieldSpec("identity", "Who are you? Contact details are optional and may stay private."),
        _FieldSpec("ranked_targets", "Which occupations are you targeting, in ranked order?"),
        _FieldSpec("experience", "What experience do you have, including dates and type?"),
        _FieldSpec("education", "What education should be included?"),
        _FieldSpec("licenses_credentials", "Which licenses or credentials apply, including expiry?"),
        _FieldSpec("skills_languages", "Which skills and languages should be included?"),
        _FieldSpec("preferences", "What location, remote, shift, travel, or industry preferences apply?"),
        _FieldSpec("compensation", "What internship and full-time compensation floors apply?"),
        _FieldSpec("availability", "What is your current and future availability?"),
    )

    def __init__(self, repository: CareerRepository, draft_id: str, answers: dict[str, OnboardingAnswer]) -> None:
        self.repository = repository
        self.draft_id = draft_id
        self.answers = answers

    @classmethod
    def start(cls, repository: CareerRepository, draft_id: str) -> "ProfileOnboarding":
        session = cls(repository, draft_id, {})
        session._persist()
        return session

    @classmethod
    def resume(cls, repository: CareerRepository, draft_id: str) -> "ProfileOnboarding":
        payload = repository.load_profile_draft(draft_id)
        if payload is None:
            return cls.start(repository, draft_id)
        raw_answers = payload.get("answers", {})
        if not isinstance(raw_answers, dict):
            return cls.start(repository, draft_id)
        answers = {
            str(field): OnboardingAnswer.model_validate(answer)
            for field, answer in raw_answers.items()
            if isinstance(answer, dict)
        }
        return cls(repository, draft_id, answers)

    @classmethod
    def profile_model(cls) -> type[CandidateProfile]:
        return CandidateProfile

    def next_question(self) -> OnboardingQuestion:
        for spec in self._FIELDS:
            if spec.field not in self.answers:
                return OnboardingQuestion(field=spec.field, prompt=spec.prompt)
        return OnboardingQuestion(field="review", prompt="Review and confirm the draft profile.")

    def answer(self, answer: OnboardingAnswer) -> None:
        field = self.next_question().field
        if field == "review":
            raise ValueError("draft is ready for review; correct a field or confirm")
        self.answers[field] = answer
        self._persist()

    def correct(self, field: str, answer: OnboardingAnswer) -> None:
        if field not in {spec.field for spec in self._FIELDS}:
            raise ValueError(f"unknown onboarding field: {field}")
        self.answers[field] = answer
        self._persist()

    def review(self) -> OnboardingReview:
        missing = [spec.field for spec in self._FIELDS if spec.field not in self.answers]
        summary_parts = [f"{field}: {answer.text}" for field, answer in self.answers.items()]
        return OnboardingReview(
            status="ready_for_confirmation" if not missing else "incomplete",
            draft_only=True,
            summary="\n".join(summary_parts),
            missing_fields=missing,
        )

    def confirm(self, confirmed_by: str) -> CandidateProfile:
        review = self.review()
        if review.status != "ready_for_confirmation":
            raise ValueError("cannot confirm an incomplete profile draft")
        confirmed_at = datetime.now(UTC)
        profile = _ProfileBuilder(self.answers, confirmed_at, confirmed_by).build()
        self.repository.save_confirmed_profile(profile)
        return profile

    def _persist(self) -> None:
        self.repository.save_profile_draft(
            self.draft_id,
            {
                "draft_id": self.draft_id,
                "answers": {
                    field: answer.model_dump(mode="json") for field, answer in self.answers.items()
                },
            },
        )


class _ProfileBuilder:
    def __init__(self, answers: dict[str, OnboardingAnswer], confirmed_at: datetime, confirmed_by: str) -> None:
        self.answers = answers
        self.confirmed_at = confirmed_at
        self.confirmed_by = confirmed_by

    def build(self) -> CandidateProfile:
        evidence = self._evidence()
        evidence_by_field = {item.provenance or "": item.evidence_id for item in evidence}
        profile_seed = "\n".join(answer.text for _, answer in sorted(self.answers.items()))
        digest = hashlib.sha256(profile_seed.encode()).hexdigest()
        return CandidateProfile(
            profile_id=f"profile_{digest[:16]}",
            version=f"v{self.confirmed_at.strftime('%Y%m%dT%H%M%SZ')}-{digest[:8]}",
            confirmed_at=self.confirmed_at,
            evidence=evidence,
            identity=self._identity(),
            ranked_targets=self._targets(evidence_by_field.get("ranked_targets", "")),
            experience=self._experience(evidence_by_field.get("experience", "")),
            education=[self.answers["education"].text],
            licenses_credentials=self._credentials(evidence_by_field.get("licenses_credentials", "")),
            skills=self._list_after_label("skills_languages", "skills"),
            languages=self._list_after_label("skills_languages", "languages"),
            preferences=self._preferences(),
        )

    def _evidence(self) -> list[CandidateEvidence]:
        items: list[CandidateEvidence] = []
        for index, field in enumerate(self.answers, start=1):
            answer = self.answers[field]
            items.append(
                CandidateEvidence(
                    evidence_id=f"ev_{field}_{index:03d}",
                    status=EvidenceStatus.CANDIDATE_CONFIRMED,
                    summary=answer.text,
                    source=answer.answered_by,
                    source_quote=answer.text,
                    provenance=field,
                    uncertainty="low",
                )
            )
        return items

    def _identity(self) -> dict[str, str]:
        return {"summary": self.answers["identity"].text, "contact": "private_or_unspecified"}

    def _targets(self, evidence_id: str) -> list[RankedTarget]:
        text = self.answers["ranked_targets"].text.lower()
        targets: list[RankedTarget] = []
        if "cashier" in text or "retail" in text or "bán" in text:
            targets.append(RankedTarget(rank=1, occupation_family="retail", title="cashier", evidence_ids=[evidence_id]))
        if "warehouse" in text or "logistics" in text or "kho" in text:
            targets.append(RankedTarget(rank=2, occupation_family="logistics", title="warehouse associate", evidence_ids=[evidence_id]))
        if "teacher" in text or "tutor" in text or "giáo" in text:
            targets.append(RankedTarget(rank=len(targets) + 1, occupation_family="education", title="teacher", evidence_ids=[evidence_id]))
        if not targets:
            targets.append(RankedTarget(rank=1, occupation_family="unknown", title=self.answers["ranked_targets"].text, evidence_ids=[evidence_id]))
        return targets

    def _experience(self, evidence_id: str) -> list[ProfileExperience]:
        text = self.answers["experience"].text
        lowered = text.lower()
        items = [
            ProfileExperience(
                title="candidate stated experience",
                start=_first_match(r"(20\d{2}-\d{2})", text),
                end=_last_match(r"(20\d{2}-\d{2})", text),
                engagement_type="full_time" if "full-time" in lowered or "full time" in lowered else "unknown",
                evidence_ids=[evidence_id],
            )
        ]
        if "volunteer" in lowered or "volunteered" in lowered:
            items.append(ProfileExperience(title="volunteer experience", engagement_type="volunteer", evidence_ids=[evidence_id]))
        return items

    def _credentials(self, evidence_id: str) -> list[ProfileCredential]:
        text = self.answers["licenses_credentials"].text
        return [ProfileCredential(label=text, expires_on=_date_match(text), evidence_ids=[evidence_id])]

    def _preferences(self) -> WorkPreferences:
        pref_text = self.answers["preferences"].text
        comp_text = self.answers["compensation"].text
        avail_text = self.answers["availability"].text
        return WorkPreferences(
            wants_internship="internship unavailable" not in avail_text.lower(),
            wants_full_time="full-time" in avail_text.lower() or "full time" in avail_text.lower(),
            preferred_locations=_locations(pref_text),
            remote_from_vietnam=False if "remote no" in pref_text.lower() else None,
            shifts=["day"] if "day" in pref_text.lower() else [],
            travel="no" if "no travel" in pref_text.lower() else None,
            industry_exclusions=_industry_exclusions(pref_text),
            internship_compensation_floor=CompensationFloor(gross_net="unknown"),
            full_time_compensation_floor=_compensation_floor(comp_text),
            availability_current=avail_text,
            availability_future=avail_text,
        )

    def _list_after_label(self, field: str, label: str) -> list[str]:
        text = self.answers[field].text
        pattern = rf"{label}:([^.;]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            return []
        return [item.strip() for item in match.group(1).split(",") if item.strip()]


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _last_match(pattern: str, text: str) -> str | None:
    matches = re.findall(pattern, text)
    return matches[-1] if matches else None


def _date_match(text: str):
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if match is None:
        return None
    from datetime import date

    return date.fromisoformat(match.group(1))


def _locations(text: str) -> list[str]:
    known = ["Ha Noi", "Hanoi", "Bac Ninh", "Ho Chi Minh", "Da Nang"]
    return [location for location in known if location.lower() in text.lower()]


def _industry_exclusions(text: str) -> list[str]:
    lowered = text.lower()
    if "exclude" not in lowered:
        return []
    excluded = lowered.split("exclude", 1)[1].replace("industry", "").replace(".", "")
    return [excluded.strip()] if excluded.strip() else []


def _compensation_floor(text: str) -> CompensationFloor:
    match = re.search(r"(\d{6,})\s*(VND|USD)\s*/\s*(month|year)", text, flags=re.IGNORECASE)
    if match is None:
        return CompensationFloor(gross_net="unknown")
    gross_net = "gross" if "gross" in text.lower() else "net" if "net" in text.lower() else "unknown"
    return CompensationFloor(
        amount=int(match.group(1)),
        currency=match.group(2).upper(),
        period=match.group(3).lower(),
        gross_net=gross_net,
    )
