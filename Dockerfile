FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY frontend/ frontend/
COPY playbooks/ playbooks/

# Non-root runtime user
RUN useradd --create-home --shell /usr/sbin/nologin copilot && chown -R copilot:copilot /app
USER copilot

EXPOSE 8000

# Migrations run as an entrypoint step so a plain `docker run` boots a usable instance;
# DATABASE_URL should point at Postgres in any shared environment.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
