FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
COPY shared ./shared
COPY services ./services

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["sh", "-c", "cd services/admin && alembic upgrade head && cd /app && uvicorn services.admin.app:app --host 0.0.0.0 --port 8000"]
