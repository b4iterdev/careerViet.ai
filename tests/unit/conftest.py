from datetime import UTC, datetime

import pytest

from mocnghe.models.profile import CandidateEvidence, CandidateProfile
from mocnghe.storage.repository import CareerRepository


@pytest.fixture
def repo(tmp_path):
    r = CareerRepository(tmp_path)
    r.save_confirmed_profile(CandidateProfile(
        profile_id="synthetic", version="v1", confirmed_at=datetime.now(UTC),
        identity={"name": "Ứng viên mẫu", "email": "synthetic@example.invalid"},
        evidence=[CandidateEvidence(evidence_id="ev1", status="candidate_confirmed",
            summary="Tình nguyện hỗ trợ khách hàng.", source="synthetic",
            provenance="experience", uncertainty="low")],
    ))
    return r

