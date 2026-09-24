from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ...models.job import Job, SourceProvenance, hash_job_identity, job_id_from_hash
from .base import BaseJobAdapter


class GenericAdapter(BaseJobAdapter):
    """Fallback adapter that extracts basic job details using standard HTML metadata."""

    name = "generic"
    domains = ()  # Matches any domain

    def parse_job(self, content: str, *, url: str) -> Job:
        soup = BeautifulSoup(content, "html.parser")

        # 1. Title
        title_el = soup.find("h1") or soup.find("title")
        raw_title = title_el.get_text(strip=True) if title_el else ""
        title = raw_title.split("|")[0].split(" - ")[0].strip() or "Untitled Job"

        # 2. Employer
        employer = ""
        og_site_name = soup.find("meta", property="og:site_name")
        if og_site_name and og_site_name.get("content"):
            employer = str(og_site_name["content"]).strip()
        if not employer:
            host = urlparse(url).hostname or ""
            parts = host.split(".")
            employer = parts[-2].title() if len(parts) >= 2 else host

        # 3. Location
        location = "unknown"

        # 4. Description & freeform
        body_el = soup.find("main") or soup.find("article") or soup.body
        body_text = body_el.get_text(separator="\n", strip=True) if body_el else content[:5000]

        freeform_lines = [
            f"Title: {title}",
            f"Company: {employer}",
            f"Location: {location}",
            f"URL: {url}",
            "",
            body_text,
        ]
        freeform_text = "\n".join(freeform_lines)

        source = SourceProvenance.model_validate(
            {
                "source_id": f"generic:{url}",
                "source_kind": "generic",
                "original_uri": url,
                "original_url": url,
                "retrieved_at": datetime.now(UTC),
            }
        )

        content_hash = hash_job_identity(freeform_text)
        return Job(
            job_id=job_id_from_hash(content_hash),
            content_hash=content_hash,
            source=source,
            title=title,
            employer=employer,
            location=location,
            description=body_text[:1000] if body_text else title,
            requirements="unknown",
            freeform_text=freeform_text,
        )
