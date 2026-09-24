FROM python:3.12-slim

# uid 1000, like every other always-on service in the stack. The docs have
# said "the process runs as uid 1000" since the secrets moved to 0644 files;
# until this line it ran as root, and the docs were the only place that said
# otherwise.
RUN useradd -m -u 1000 inkframe

# Pillow needs no build toolchain for the wheels we pin, so this stays small.
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Every file the service imports must be listed here. This repository has
# shipped a service four times with an import that existed in the tree and not
# in the image; the test below parses the imports and fails if one is missing.
COPY src/immich.py src/app.py ./

# /data is the state directory (STATE_FILE, the persisted frame). Owning it
# here means a FRESH named volume inherits uid 1000 when Docker first mounts
# it over this directory, so a new install never needs the one-shot chown. A
# volume that already exists as root:root -- every install that ran the root
# image -- does not inherit anything; that case is the `*-volume-init`
# service in docker-compose.yml, which chowns in place and keeps the contents.
RUN mkdir -p /data && chown inkframe:inkframe /data
USER inkframe

ENV PYTHONUNBUFFERED=1 \
    LISTEN_HOST=0.0.0.0 \
    LISTEN_PORT=8099

EXPOSE 8099

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=5).status==200 else 1)"

CMD ["python", "app.py"]
