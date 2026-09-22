import pytest

from mocnghe.storage.repository import CareerRepository


def test_create_persist_and_approve(repo):
    from mocnghe.cv import CVService
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="vi")
    assert cv.claims[0].text == "Tình nguyện hỗ trợ khách hàng."
    assert not s.approved(cv.id)
    loaded = CVService(CareerRepository(repo.workspace)).get(cv.id)
    assert loaded == cv
    with pytest.raises(ValueError, match="hash"):
        s.approve(cv.id, "0" * 64)
    s.approve(cv.id, s.content_hash(cv))
    assert s.approved(cv.id)


def test_revision_invalidates_approval_and_rejects_fabricated_quotes(repo):
    from mocnghe.cv import CVService
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    s.approve(cv.id, s.content_hash(cv))
    claims = [c.model_dump() for c in cv.claims]
    claims[0]["text"] = "Volunteered in customer support."
    claims[0]["mode"] = "proposed"
    revision = s.revise(cv.id, claims, provenance="human-proposed")
    assert revision.id != cv.id and not s.approved(revision.id)
    assert s.get(cv.id) == cv
    claims[0]["source_quote"] = "Invented revenue growth"
    with pytest.raises(ValueError, match="quote"):
        s.revise(cv.id, claims, provenance="human-proposed")


@pytest.mark.parametrize("ids", [["missing"], ["ev1", "ev1"], []])
def test_invalid_selection(repo, ids):
    from mocnghe.cv import CVService
    with pytest.raises(ValueError):
        CVService(repo).create("v1", ids, language="vi")


def test_render_review_gate_accents_and_collision(repo, tmp_path):
    from pypdf import PdfReader

    from mocnghe.cv import CVService
    from mocnghe.cv_render import export_cv
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="vi", identity_keys=["name"])
    target = tmp_path / "bundle"
    with pytest.raises(PermissionError):
        export_cv(s, cv.id, target, max_pages=1)
    assert not target.exists()
    s.approve(cv.id, s.content_hash(cv))
    export_cv(s, cv.id, target, max_pages=1)
    reader = PdfReader(target / "cv.pdf")
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Ứng viên mẫu" in text and "Tình nguyện hỗ trợ khách hàng." in text
    assert "synthetic@example.invalid" not in text
    assert (target / "cv.json").exists()
    with pytest.raises(FileExistsError):
        export_cv(s, cv.id, target, max_pages=1)


def test_canonical_tampering_rejected(repo):
    from mocnghe.cv import CVService
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="vi")
    with repo.connect() as db:
        db.execute("UPDATE profiles SET payload_json=replace(payload_json, ?, ?)",
                   ("khách hàng", "bệnh nhân"))
    with pytest.raises(ValueError, match="stale"):
        s.approve(cv.id, s.content_hash(cv))
