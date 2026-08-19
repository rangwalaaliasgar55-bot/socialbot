FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY socialbot ./socialbot

RUN pip install --no-cache-dir .

ENV SOCIALBOT_DB=/data/socialbot.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8000

CMD ["socialbot", "dashboard", "--host", "0.0.0.0", "--port", "8000"]
