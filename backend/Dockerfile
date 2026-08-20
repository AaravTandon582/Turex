# Two stages so the image that ships does not carry a build toolchain it will never use.
FROM python:3.13-slim AS builder

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies before source: this layer is cached until pyproject.toml changes, so editing
# code does not reinstall the world.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY atlas ./atlas
RUN pip install --no-cache-dir --no-deps .


FROM python:3.13-slim AS runtime

# Runs as a user with no privileges. A container process that does not need root should not
# have it, and PDF parsing on uploaded files is exactly the kind of code to be careful about.
RUN useradd --create-home --uid 10001 atlas
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=atlas:atlas atlas ./atlas
COPY --chown=atlas:atlas alembic ./alembic
COPY --chown=atlas:atlas alembic.ini ./

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STORAGE_ROOT=/data/storage

# Uploaded PDFs live on a volume, not in the image: a container is disposable and a library
# is not.
RUN mkdir -p /data/storage && chown -R atlas:atlas /data
VOLUME ["/data"]

USER atlas
EXPOSE 8000

# The readiness endpoint checks the database, so an unhealthy container is one that cannot
# actually serve a request rather than one whose process merely exists.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "atlas.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
