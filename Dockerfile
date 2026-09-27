# Container image for Koyeb (or any Docker host). Python 3.11, all wheels are prebuilt — no system libraries needed.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Koyeb injects PORT (default 8000). One worker fits the 512 MB free instance; raise WEB_CONCURRENCY on bigger ones.
ENV PORT=8000 WEB_CONCURRENCY=1 GUNICORN_THREADS=4 APP_TIMEZONE=Asia/Amman SESSION_COOKIE_SECURE=1
EXPOSE 8000

# Migrations + base data (+ first admin / optional demo) run at every start; all idempotent.
CMD ["sh", "-c", "flask --app wsgi.py db upgrade && flask --app wsgi.py seed-base && exec gunicorn wsgi:app --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --threads ${GUNICORN_THREADS} --timeout 120 --access-logfile -"]
