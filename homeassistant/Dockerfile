FROM python:3.13-slim

# jq parses the options Supervisor writes to /data/options.json.
RUN apt-get update \
    && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Resolve dependencies from the committed lockfile, then install the project
# itself without re-resolving, so the image matches `uv sync --frozen` exactly.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps . \
    && pip uninstall -y uv \
    && rm /tmp/requirements.txt

# Prebuilt CaudalNet bundle; `make ha-app` puts it here.
COPY web/ ./web/

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
