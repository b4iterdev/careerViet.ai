from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mocnghe.ingestion.results import IngestionState, SourceResult, SourceStats


def test_success_and_empty_require_validated_schema() -> None:
    stats = SourceStats(source_id="itviec", started_at=datetime.now(UTC))

    with pytest.raises(ValidationError):
        SourceResult(source_id="itviec", state=IngestionState.SUCCESS, stats=stats)

    with pytest.raises(ValidationError):
        SourceResult(source_id="itviec", state=IngestionState.EMPTY, stats=stats)

    result = SourceResult(
        source_id="itviec",
        state=IngestionState.EMPTY,
        stats=stats,
        schema_validated=True,
    )

    assert result.state is IngestionState.EMPTY
    assert result.jobs == []


def test_stats_record_status_bytes_filters_and_cache_hits() -> None:
    stats = SourceStats(source_id="vietnamworks", started_at=datetime(2026, 9, 15, tzinfo=UTC))

    stats.record_http(status_code=200, latency_ms=12, bytes_received=512)
    stats.record_http(status_code=429, latency_ms=25, bytes_received=0)
    stats.record_filter("keyword:C++")
    stats.cache_hits += 1
    stats.parsed_unique_count = 2
    stats.missing_required_fields = 1

    assert stats.requests == 2
    assert stats.status_codes == [200, 429]
    assert stats.bytes_received == 512
    assert stats.latency_ms == 37
    assert stats.filters == ["keyword:C++"]
    assert stats.cache_hits == 1
    assert stats.parsed_unique_count == 2
    assert stats.missing_required_fields == 1
