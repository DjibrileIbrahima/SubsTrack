import contextvars
import json
import logging
import os
from logging import LogRecord

# Correlation id for the in-flight request. Set by RequestLoggingMiddleware and
# read by the log-record factory below, so every log line — not just the access
# log — carries the request id. "-" when logging outside a request (startup, jobs).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Optional: stamp the active OpenTelemetry trace id onto logs when tracing is on.
try:
    from opentelemetry import trace as _otel_trace
except Exception:  # opentelemetry not installed
    _otel_trace = None

# Standard LogRecord fields we never want to duplicate in JSON output.
# request_id is emitted explicitly below, so it's listed here to avoid a dup.
_STDLIB_FIELDS = frozenset((
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime", "request_id",
))


def _install_record_factory() -> None:
    """Wrap the log-record factory so every record gets request_id (and trace_id
    when a span is active) from the current context at creation time. Idempotent."""
    existing = logging.getLogRecordFactory()
    if getattr(existing, "_substrack_wrapped", False):
        return

    def factory(*args, **kwargs):
        record = existing(*args, **kwargs)
        record.request_id = request_id_var.get()
        if _otel_trace is not None:
            span_ctx = _otel_trace.get_current_span().get_span_context()
            if getattr(span_ctx, "is_valid", False):
                record.trace_id = format(span_ctx.trace_id, "032x")
        return record

    factory._substrack_wrapped = True
    logging.setLogRecordFactory(factory)


class _JsonFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        record.message = record.getMessage()
        obj: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
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
    _install_record_factory()

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    use_json = os.getenv("LOG_FORMAT", "text") == "json"

    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    fmt: logging.Formatter = (
        _JsonFormatter() if use_json
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s")
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
