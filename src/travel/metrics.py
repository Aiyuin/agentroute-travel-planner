import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

REQUESTS = Counter(
    "agentroute_http_requests_total", "Completed HTTP requests", ["method", "route", "status"]
)
LATENCY = Histogram(
    "agentroute_http_seconds",
    "HTTP response creation latency, excluding streamed body",
    ["route"],
    buckets=(0.01, 0.1, 0.5, 1, 5, 15, 30, 60, 120),
)


def install_metrics(app, router):
    @app.middleware("http")
    async def metrics_middleware(request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        # Route templates prevent user IDs from creating unbounded cardinality.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        LATENCY.labels(route).observe(time.monotonic() - started)
        return response

    @router.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
