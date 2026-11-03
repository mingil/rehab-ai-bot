FROM python:3.11-slim

ENV TZ=Asia/Seoul
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends tzdata sqlite3 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ ./config/
COPY src/ ./src/

RUN mkdir -p /app/config /app/data/reports /app/logs \
    && chmod -R 777 /app/config /app/data /app/logs

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os, time; p='/tmp/rehab_ai_bot_heartbeat'; assert os.path.exists(p) and (time.time() - os.path.getmtime(p)) < 3900" || exit 1

CMD ["python", "-u", "src/run.py"]
