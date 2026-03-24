"""OpenTelemetry metrics emission for Project Oracle."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from opentelemetry.metrics import CallbackOptions, Observation

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics import MeterProvider

    from oracle.storage.store import OracleStore

logger = logging.getLogger(__name__)

_METER_NAME = "project-oracle"


class Telemetry:
    """Wraps OTel meter and instruments for Oracle metrics emission.

    When meter_provider is None, all recording methods are silent no-ops.
    When store is provided, observable gauges query it for adoption and hit rates.
    Gauge callbacks open fresh SQLite connections because the OTel SDK invokes
    them from a background thread, and SQLite connections are thread-bound.
    """

    def __init__(
        self,
        meter_provider: MeterProvider | None = None,
        store: OracleStore | None = None,
    ) -> None:
        self._db_path: Path | None = store.db_path if store is not None else None

        if meter_provider is None:
            self._tool_calls = None
            self._cache_hits = None
            self._tokens_saved = None
            return

        meter = meter_provider.get_meter(_METER_NAME)

        self._tool_calls = meter.create_counter(
            name="oracle.tool_calls",
            description="Number of oracle tool invocations",
        )
        self._cache_hits = meter.create_counter(
            name="oracle.cache_hits",
            description="Number of cache hits across oracle tools",
        )
        self._tokens_saved = meter.create_counter(
            name="oracle.tokens_saved",
            description="Cumulative tokens saved by cache hits",
        )

        if store is not None:
            meter.create_observable_gauge(
                name="oracle.adoption_rate",
                callbacks=[self._observe_adoption_rate],
                description="Oracle adoption rate per tool category",
            )
            meter.create_observable_gauge(
                name="oracle.cache_hit_rate",
                callbacks=[self._observe_cache_hit_rate],
                description="Overall cache hit rate across oracle tools",
            )

    def _read_only_store(self) -> OracleStore | None:
        """Open a fresh OracleStore for the current thread (gauge callback safe)."""
        if self._db_path is None:
            return None
        from oracle.storage.store import OracleStore

        return OracleStore(self._db_path)

    def record_tool_call(
        self,
        tool_name: str,
        session_id: str,
        cache_hit: bool,
        tokens_saved: int,
    ) -> None:
        """Record a tool invocation, incrementing counters as appropriate."""
        if self._tool_calls is None:
            return

        attributes = {"tool_name": tool_name, "session_id": session_id}
        self._tool_calls.add(1, attributes)

        if cache_hit and self._cache_hits is not None:
            self._cache_hits.add(1, {"tool_name": tool_name})

        if tokens_saved > 0 and self._tokens_saved is not None:
            self._tokens_saved.add(tokens_saved, {"tool_name": tool_name})

    def _observe_adoption_rate(self, options: CallbackOptions) -> list[Observation]:
        store = self._read_only_store()
        if store is None:
            return []

        try:
            rates = store.get_adoption_rates()
            if not rates:
                return []

            observations: list[Observation] = []
            for category, data in rates.items():
                observations.append(
                    Observation(value=data["rate"], attributes={"category": category})
                )
            return observations
        except Exception:
            logger.exception("Failed to observe adoption rate")
            return []
        finally:
            store.close()

    def _observe_cache_hit_rate(self, options: CallbackOptions) -> list[Observation]:
        store = self._read_only_store()
        if store is None:
            return []

        try:
            cumulative = store.get_cumulative_stats()
            total_hits = cumulative["total_cache_hits"]
            total_calls = store.get_cumulative_call_count()

            if total_calls == 0:
                return [Observation(value=0.0)]

            rate = total_hits / total_calls
            return [Observation(value=rate)]
        except Exception:
            logger.exception("Failed to observe cache hit rate")
            return []
        finally:
            store.close()


def create_telemetry(
    endpoint: str | None = None,
    store: OracleStore | None = None,
) -> Telemetry:
    """Factory that wires up an OTLP HTTP exporter and returns a Telemetry instance.

    Reads OTEL_EXPORTER_OTLP_METRICS_ENDPOINT from environment if endpoint is not provided.
    Defaults to http://localhost:4318/v1/metrics (full OTLP HTTP metrics path).

    Note: OTLPMetricExporter appends /v1/metrics to bare base URLs, causing
    double-path 404s. We pass the full path to avoid this.
    """
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    resolved_endpoint = endpoint or os.environ.get(
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://localhost:4318/v1/metrics"
    )

    exporter = OTLPMetricExporter(endpoint=resolved_endpoint)
    reader = PeriodicExportingMetricReader(exporter)
    provider = MeterProvider(metric_readers=[reader])

    return Telemetry(meter_provider=provider, store=store)
