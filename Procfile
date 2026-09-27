web: flask --app wsgi.py db upgrade && flask --app wsgi.py seed-base && gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-4} --timeout 120
