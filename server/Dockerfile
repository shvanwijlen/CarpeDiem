FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY carpediem_store ./carpediem_store

# The SQLite database lives on a mounted volume (see docker-compose.yml).
ENV SQLITE_PATH=/data/carpediem.db
VOLUME /data
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3)" || exit 1

CMD ["python", "-m", "carpediem_store"]
