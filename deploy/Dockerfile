FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agents ./agents
COPY backend ./backend
COPY planner ./planner
COPY reports ./reports
COPY router ./router
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data && chown -R appuser /data /app
USER appuser
ENV DATAFORGE_PERSISTENCE=sqlite \
    DATAFORGE_DB_PATH=/data/dataforge.db \
    DATAFORGE_AUTH_DB=/data/auth.db \
    DATAFORGE_TEAMS_DB=/data/teams.db \
    DATAFORGE_VAULT_DB=/data/vault.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
