# UNTESTED: Docker was not available on the author's machine when this was written.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

# Run as a non-root user.
RUN useradd --create-home appuser
USER appuser

# Default: the API. The worker overrides the command (see docker-compose.yml).
EXPOSE 8000
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
