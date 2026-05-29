import json
import logging
import os
from logging import LogRecord

# Standard LogRecord fields we never want to duplicate in JSON output
_STDLIB_FIELDS = frozenset((
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
))


class _JsonFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        record.message = record.getMessage()
        obj: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        # Include any extra={} fields passed to the logger call
        for k, v in record.__dict__.items():
            if k not in _STDLIB_FIELDS and not k.startswith("_"):
                obj[k] = v
        return json.dumps(obj, default=str)


def configure_logging() -> None:
    """Configure root logger. Set LOG_FORMAT=json for structured output (default in production)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    use_json = os.getenv("LOG_FORMAT", "text") == "json"

    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    fmt: logging.Formatter = (
        _JsonFormatter() if use_json
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    for handler in root.handlers:
        handler.setFormatter(fmt)


def init_sentry() -> None:
    """Init Sentry. No-op when SENTRY_DSN is unset."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        integrations = [
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ]
        try:
            from sentry_sdk.integrations.arq import ArqIntegration
            integrations.append(ArqIntegration())
        except ImportError:
            pass

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENV", "production"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            integrations=integrations,
            send_default_pii=False,
        )
        logging.getLogger(__name__).info("Sentry initialized")
    except ImportError:
        logging.getLogger(__name__).warning("sentry-sdk not installed; Sentry disabled")


def init_otel(app=None) -> None:
    """Init OpenTelemetry tracing. No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.

    Compatible with Grafana Cloud, Honeycomb, and any OTLP-compatible backend.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "substrack-backend")}
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)

        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)

        logging.getLogger(__name__).info(
            "OpenTelemetry initialized", extra={"otlp_endpoint": endpoint}
        )
    except ImportError:
        logging.getLogger(__name__).warning(
            "opentelemetry packages not installed; tracing disabled"
        )
