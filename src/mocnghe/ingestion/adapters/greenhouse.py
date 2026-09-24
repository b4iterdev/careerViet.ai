from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ...models.job import Job, SourceProvenance, hash_job_identity, job_id_from_hash
from .base import BaseJobAdapter


class GreenhouseAdapter(BaseJobAdapter):
    """Adapter for Greenhouse job boards (boards.greenhouse.io, job-boards.eu.greenhouse.io)."""

    name = "greenhouse"
    domains = ("greenhouse.io",)

    def parse_job(self, content: str, *, url: str) -> Job:
        soup = BeautifulSoup(content, "html.parser")

        # 1. Title
        title_el = (
            soup.find("h1", class_="app-title")
            or soup.find("h1", class_="job__title")
            or soup.find("h1")
        )
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = str(og_title["content"]).split(" at ")[0].strip()

        if not title:
            title = "Unknown Role"

        # 2. Employer
        company_el = (
            soup.find("span", class_="company-name")
            or soup.find("span", class_="company")
            or soup.find("div", class_="company-name")
        )
        employer = company_el.get_text(strip=True) if company_el else ""
        if not employer:
            # Fallback: extract company token from URL path: /<company_token>/jobs/<job_id>
            path_parts = [p for p in urlparse(url).path.split("/") if p]
            if path_parts:
                employer = path_parts[0].replace("-", " ").title()
            else:
                employer = "Unknown Employer"

        # 3. Location
        loc_el = (
            soup.find("div", class_="location")
            or soup.find("span", class_="location")
            or soup.find(class_="job__location")
        )
        location = loc_el.get_text(strip=True) if loc_el else "unknown"

        # 4. Content / Description
        content_el = soup.find(id="content") or soup.find(class_="job__description") or soup.body
        body_text = content_el.get_text(separator="\n", strip=True) if content_el else ""

        # Build clean freeform text
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
                "source_id": f"greenhouse:{url}",
                "source_kind": "greenhouse",
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
