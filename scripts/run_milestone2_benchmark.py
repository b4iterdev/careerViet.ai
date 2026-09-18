from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx

from careerviet.ingestion.http_client import SafeHttpClient
from careerviet.ingestion.itviec import search_itviec
from careerviet.ingestion.results import SourceResult
from careerviet.ingestion.source_policy import discover_source_policy
from careerviet.ingestion.vietnamworks import AUTHORIZED_SEARCH_URL, search_vietnamworks

ITVIEC_URL = "https://itviec.com/it-jobs/c-plus-plus/ha-noi"
MAX_REQUESTS = 12

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded milestone 2 live HTTP benchmark")
    _ = parser.add_argument(
        "--output",
        default="docs/benchmarks/milestone-2-live-benchmark.json",
        help="JSON artifact path",
    )
    args = parser.parse_args()

    artifact = run_benchmark()
    output = Path(cast(str, args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")


def run_benchmark() -> JsonObject:
    started_at = datetime.now(UTC)
    sources: dict[str, JsonValue] = {}
    total_requests = 0
    artifact: JsonObject = {
        "benchmark": "milestone-2-live-http-ingestion",
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": None,
        "max_requests_total": MAX_REQUESTS,
        "policy": "bounded public HTTPS only; no credentials, browser, bypass, submissions, or invented payloads",
        "sources": sources,
        "total_requests": 0,
    }
    with tempfile.TemporaryDirectory(prefix="hermes-benchmark-cache-") as cache_root:
        cache_path = Path(cache_root)
        itviec_policy = _discover_policy(cache_path / "itviec", {"itviec.com"}, ITVIEC_URL)
        sources["itviec_policy"] = itviec_policy
        total_requests += int(cast(int, itviec_policy["requests"]))

        remaining = MAX_REQUESTS - total_requests
        if itviec_policy["state"] == "success" and remaining > 1:
            client = SafeHttpClient(cache_dir=cache_path / "itviec-search", allowed_hosts={"itviec.com"})
            result = search_itviec(client=client, keyword="C++", location="Hà Nội", request_budget=min(remaining, 4))
            sources["itviec_search"] = _result_summary(result)
            total_requests += result.stats.requests
        else:
            sources["itviec_search"] = {
                "state": "policy_unverified",
                "message": "live extraction skipped because policy discovery was not successful within budget",
                "requests": 0,
                "extracted_unique_count": 0,
            }

        remaining = MAX_REQUESTS - total_requests
        if remaining > 0:
            vietnamworks_policy = _discover_policy(
                cache_path / "vietnamworks",
                {"ms.vietnamworks.com"},
                AUTHORIZED_SEARCH_URL,
            )
            sources["vietnamworks_policy"] = vietnamworks_policy
            total_requests += int(cast(int, vietnamworks_policy["requests"]))
        else:
            sources["vietnamworks_policy"] = {"state": "skipped_budget_exhausted", "requests": 0}
        vietnamworks_search = search_vietnamworks(cache_dir=cache_path / "vietnamworks-search", live=True)
        sources["vietnamworks_search"] = _result_summary(vietnamworks_search)
    artifact["total_requests"] = total_requests
    artifact["finished_at_utc"] = datetime.now(UTC).isoformat()
    return artifact


def _discover_policy(cache_dir: Path, allowed_hosts: set[str], observed_url: str) -> JsonObject:
    client = SafeHttpClient(cache_dir=cache_dir, allowed_hosts=allowed_hosts)
    try:
        result = discover_source_policy(client, observed_url)
    except (OSError, ValueError, RuntimeError, TimeoutError, httpx.HTTPError) as error:
        return {
            "state": "error",
            "message": f"{type(error).__name__}: {error}",
            "requests": 0,
            "evidence": [],
        }
    return {
        "state": result.state.value,
        "message": result.message,
        "requests": result.stats.requests,
        "status_codes": result.stats.status_codes,
        "bytes": result.stats.bytes_received,
        "latency_ms": result.stats.latency_ms,
        "evidence": [item.model_dump(mode="json") for item in result.policy_evidence],
    }


def _result_summary(result: SourceResult) -> JsonObject:
    return {
        "state": result.state.value,
        "message": result.message,
        "requests": result.stats.requests,
        "status_codes": result.stats.status_codes,
        "bytes": result.stats.bytes_received,
        "latency_ms": result.stats.latency_ms,
        "extracted_unique_count": result.stats.parsed_unique_count,
        "missing_required_fields": result.stats.missing_required_fields,
        "duplicates": result.stats.duplicates,
        "cache_hits": result.stats.cache_hits,
        "filtered_count": result.stats.filtered_count,
    }


if __name__ == "__main__":
    main()
