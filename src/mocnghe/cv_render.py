"""Bounded local renderer. All user text is escaped data, never markup or code."""
import io
import os
import shutil
import tempfile
from html import escape
from importlib.resources import files
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

LABELS = {
    "en": {"title": "Curriculum Vitae", "experience": "Experience", "education": "Education",
           "skills": "Skills", "credentials": "Credentials", "other": "Additional evidence"},
    "vi": {"title": "Hồ sơ ứng tuyển", "experience": "Kinh nghiệm", "education": "Học vấn",
           "skills": "Kỹ năng", "credentials": "Chứng chỉ", "other": "Thông tin bổ sung"},
}


def publish_bundle(target: Path, contents: dict[str, bytes]):
    """Reserve a new directory exclusively; rollback owned output on every failure."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("output already exists; choose a new directory")
    if not target.parent.is_dir():
        raise ValueError("output parent must exist")
    with tempfile.TemporaryDirectory(prefix=".mocnghe-export-", dir=target.parent) as tmp:
        staging = Path(tmp)
        for name, data in contents.items():
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("invalid bundle member")
            (staging / name).write_bytes(data)
        # mkdir is exclusive, avoiding rename's replacement of an existing empty directory.
        target.mkdir(mode=0o700)
        try:
            for name in contents:
                os.replace(staging / name, target / name)
        except BaseException:
            shutil.rmtree(target)
            raise


def render_pdf(cv, max_pages=2):
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("page budget must be between 1 and 10")
    font = "MocNgheNotoSans"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, str(files("mocnghe.assets").joinpath(
            "fonts/NotoSans-Regular.ttf"))))
    texts = list(cv.identity.values()) + [c.text for c in cv.claims]
    glyphs = pdfmetrics.getFont(font).face.charToGlyph
    if any(ord(ch) not in glyphs for text in texts for ch in text if ch not in "\n\r\t"):
        raise ValueError("selected text contains glyphs unsupported by the bundled font")
    body = ParagraphStyle("body", fontName=font, fontSize=10.5, leading=15, spaceAfter=7)
    heading = ParagraphStyle("heading", parent=body, fontSize=13, leading=19,
                             spaceBefore=12, spaceAfter=6, keepWithNext=True)
    title = ParagraphStyle("title", parent=body, fontSize=20, leading=28, spaceAfter=12)
    labels = LABELS[cv.language]
    def p(text, style=body):
        return Paragraph(escape(text).replace("\n", "<br/>"), style)
    story = [p(cv.identity.get("name", labels["title"]), title)]
    for key, value in cv.identity.items():
        if key != "name":
            story.append(p(value))
    for section in ("experience", "education", "skills", "credentials", "other"):
        claims = [c for c in cv.claims if c.section == section]
        if not claims:
            continue
        story.append(p(labels[section], heading))
        for claim in claims:
            story.append(p(claim.text))
    story.append(Spacer(1, 5))
    buf = io.BytesIO()
    def check_page(canvas, document):
        if document.page > max_pages:
            raise ValueError("CV exceeds page budget; shorten content or increase --max-pages")
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=48, rightMargin=48,
                            topMargin=42, bottomMargin=42, title=labels["title"], author="")
    doc.build(story, onFirstPage=check_page, onLaterPages=check_page)
    return buf.getvalue()


def export_cv(service, cv_id, target, *, max_pages=2):
    cv = service.get(cv_id)
    if not service.approved(cv_id):
        raise PermissionError("review and approve exact CV content before export")
    pdf = render_pdf(cv, max_pages)
    publish_bundle(Path(target), {"cv.pdf": pdf, "cv.json": cv.model_dump_json(indent=2).encode()})
