"""Tests for OpenTelemetry metrics emission via oracle.telemetry."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from oracle.storage.store import OracleStore
from oracle.telemetry import Telemetry, create_telemetry


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def meter_provider(metric_reader: InMemoryMetricReader) -> MeterProvider:
    return MeterProvider(metric_readers=[metric_reader])


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


def _get_metric_value(
    metric_reader: InMemoryMetricReader, metric_name: str
) -> list[dict[str, object]]:
    """Extract data points for a named metric from the in-memory reader."""
    data = metric_reader.get_metrics_data()
    results: list[dict[str, object]] = []
    if data is None:
        return results
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == metric_name:
                    for dp in metric.data.data_points:
                        results.append(
                            {
                                "value": dp.value,
                                "attributes": dict(dp.attributes) if dp.attributes else {},
                            }
                        )
    return results


@pytest.mark.medium
class DescribeTelemetrySetup:
    def it_creates_a_telemetry_instance_with_meter_provider(
        self, meter_provider: MeterProvider
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)

        assert telemetry._tool_calls is not None

    def it_creates_a_telemetry_instance_without_meter_provider(self) -> None:
        telemetry = Telemetry(meter_provider=None)

        assert telemetry._tool_calls is None


@pytest.mark.medium
class DescribeRecordToolCall:
    def it_increments_tool_calls_counter(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=False, tokens_saved=0
        )

        points = _get_metric_value(metric_reader, "oracle.tool_calls")
        assert len(points) == 1
        assert points[0]["value"] == 1
        assert points[0]["attributes"] == {"tool_name": "oracle_read", "session_id": "sess-1"}

    def it_increments_cache_hits_counter_on_hit(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=True, tokens_saved=500
        )

        points = _get_metric_value(metric_reader, "oracle.cache_hits")
        assert len(points) == 1
        assert points[0]["value"] == 1
        assert points[0]["attributes"] == {"tool_name": "oracle_read"}

    def it_does_not_increment_cache_hits_on_miss(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=False, tokens_saved=0
        )

        points = _get_metric_value(metric_reader, "oracle.cache_hits")
        assert len(points) == 0

    def it_increments_tokens_saved_counter(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=True, tokens_saved=500
        )

        points = _get_metric_value(metric_reader, "oracle.tokens_saved")
        assert len(points) == 1
        assert points[0]["value"] == 500
        assert points[0]["attributes"] == {"tool_name": "oracle_read"}

    def it_does_not_increment_tokens_saved_when_zero(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=False, tokens_saved=0
        )

        points = _get_metric_value(metric_reader, "oracle.tokens_saved")
        assert len(points) == 0

    def it_accumulates_multiple_tool_calls(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=True, tokens_saved=100
        )
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=True, tokens_saved=200
        )

        points = _get_metric_value(metric_reader, "oracle.tool_calls")
        assert len(points) == 1
        assert points[0]["value"] == 2

        token_points = _get_metric_value(metric_reader, "oracle.tokens_saved")
        assert len(token_points) == 1
        assert token_points[0]["value"] == 300

    def it_handles_no_meter_provider_gracefully(self, metric_reader: InMemoryMetricReader) -> None:
        no_op_provider = MeterProvider(metric_readers=[metric_reader])
        telemetry = Telemetry(meter_provider=None)

        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=True, tokens_saved=500
        )

        _ = Telemetry(meter_provider=no_op_provider)  # Kept alive: triggers metric collection
        points = _get_metric_value(metric_reader, "oracle.tool_calls")
        assert len(points) == 0

    def it_increments_cache_hits_but_not_tokens_when_hit_with_zero_saved(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=True, tokens_saved=0
        )

        cache_points = _get_metric_value(metric_reader, "oracle.cache_hits")
        assert len(cache_points) == 1
        assert cache_points[0]["value"] == 1

        token_points = _get_metric_value(metric_reader, "oracle.tokens_saved")
        assert len(token_points) == 0

    def it_does_not_increment_tokens_saved_for_negative_values(
        self, meter_provider: MeterProvider, metric_reader: InMemoryMetricReader
    ) -> None:
        telemetry = Telemetry(meter_provider=meter_provider)
        telemetry.record_tool_call(
            tool_name="oracle_read", session_id="sess-1", cache_hit=False, tokens_saved=-100
        )

        token_points = _get_metric_value(metric_reader, "oracle.tokens_saved")
        assert len(token_points) == 0


@pytest.mark.medium
class DescribeObservableGauges:
    def it_reports_adoption_rate_per_category(
        self,
        meter_provider: MeterProvider,
        metric_reader: InMemoryMetricReader,
        store: OracleStore,
    ) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 2000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 3000)

        _ = Telemetry(meter_provider=meter_provider, store=store)  # prevent GC
        points = _get_metric_value(metric_reader, "oracle.adoption_rate")

        by_category = {str(p["attributes"].get("category", "")): p["value"] for p in points}
        assert by_category["read"] == pytest.approx(1 / 3, abs=0.01)

    def it_reports_cache_hit_rate(
        self,
        meter_provider: MeterProvider,
        metric_reader: InMemoryMetricReader,
        store: OracleStore,
    ) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", False, 0, 2000)
        store.log_interaction("sess-1", "oracle_grep", "pat", True, 200, 3000)

        _ = Telemetry(meter_provider=meter_provider, store=store)  # prevent GC
        points = _get_metric_value(metric_reader, "oracle.cache_hit_rate")

        assert len(points) == 1
        assert points[0]["value"] == pytest.approx(2 / 3, abs=0.01)

    def it_reports_zero_adoption_rate_with_empty_store(
        self,
        meter_provider: MeterProvider,
        metric_reader: InMemoryMetricReader,
        store: OracleStore,
    ) -> None:
        # Empty store returns no categories, so no observations (unlike hit_rate which reports 0.0)
        _ = Telemetry(meter_provider=meter_provider, store=store)  # prevent GC
        points = _get_metric_value(metric_reader, "oracle.adoption_rate")

        assert len(points) == 0

    def it_reports_zero_cache_hit_rate_with_empty_store(
        self,
        meter_provider: MeterProvider,
        metric_reader: InMemoryMetricReader,
        store: OracleStore,
    ) -> None:
        _ = Telemetry(meter_provider=meter_provider, store=store)  # prevent GC
        points = _get_metric_value(metric_reader, "oracle.cache_hit_rate")

        assert len(points) == 1
        assert points[0]["value"] == pytest.approx(0.0)

    def it_reports_no_gauges_when_store_is_none(
        self,
        meter_provider: MeterProvider,
        metric_reader: InMemoryMetricReader,
    ) -> None:
        _ = Telemetry(meter_provider=meter_provider, store=None)  # prevent GC
        adoption_points = _get_metric_value(metric_reader, "oracle.adoption_rate")
        hit_rate_points = _get_metric_value(metric_reader, "oracle.cache_hit_rate")

        assert len(adoption_points) == 0
        assert len(hit_rate_points) == 0


@pytest.mark.medium
class DescribeCreateTelemetry:
    def it_creates_telemetry_with_default_otlp_endpoint(self) -> None:
        telemetry = create_telemetry(store=None)

        assert isinstance(telemetry, Telemetry)

    def it_creates_telemetry_with_custom_endpoint(self) -> None:
        telemetry = create_telemetry(endpoint="http://localhost:9999", store=None)

        assert isinstance(telemetry, Telemetry)

    def it_creates_telemetry_with_store(self, store: OracleStore) -> None:
        telemetry = create_telemetry(store=store)

        assert isinstance(telemetry, Telemetry)

    def it_creates_telemetry_using_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:9999")

        telemetry = create_telemetry(store=None)

        assert isinstance(telemetry, Telemetry)
