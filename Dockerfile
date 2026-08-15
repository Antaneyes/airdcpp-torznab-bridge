FROM python:3.13-alpine AS builder
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && rm -rf /opt/venv/lib/python*/site-packages/pip* /opt/venv/bin/pip*

FROM python:3.13-alpine
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/bin/pip* \
    && addgroup -g 10001 -S bridge \
    && adduser -u 10001 -S -D -H -h /app -G bridge bridge
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=bridge:bridge app ./app
RUN mkdir /app/data && chown bridge:bridge /app/data
USER bridge
EXPOSE 8000
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
