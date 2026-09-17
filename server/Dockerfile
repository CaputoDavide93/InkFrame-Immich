FROM python:3.12-slim

# Pillow needs no build toolchain for the wheels we pin, so this stays small.
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Every file the service imports must be listed here. This repository has
# shipped a service four times with an import that existed in the tree and not
# in the image; the test below parses the imports and fails if one is missing.
COPY src/immich.py src/app.py ./

ENV PYTHONUNBUFFERED=1 \
    LISTEN_HOST=0.0.0.0 \
    LISTEN_PORT=8099

EXPOSE 8099

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=5).status==200 else 1)"

CMD ["python", "app.py"]
