# FamilyBridge API image (Plan §3.1 packaging). Demo data only in Stage 1.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/backend

COPY backend/requirements.lock ./
RUN pip install -r requirements.lock

COPY backend/ ./
COPY content/ /srv/content/
ENV CONTENT_DIR=/srv/content

RUN useradd --system --uid 10001 app && chown -R app /srv
USER app

EXPOSE 8000
# Apply migrations, then serve. Content is validated at startup (fails fast if invalid).
CMD ["sh", "-c", "python -m app.cli migrate && exec uvicorn app.asgi:app --host 0.0.0.0 --port 8000 --proxy-headers"]
