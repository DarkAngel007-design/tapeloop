# Runs the tapeloop CLI. Deliberately unremarkable — the charter says this is not a
# hosted service, so there is no server, no queue and no supervisor here.
#
#   docker build -t tapeloop .
#   docker run --rm -v "$PWD:/work" -w /work -e OPENAI_API_KEY tapeloop run "…"
#
# Note the agent's own sandbox is a separate concern: DockerExecutor starts its own
# container for tool commands. This image runs the harness, not the tools.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Unprivileged by default. The harness executes model-authored commands; running it
# as root would make the weakest link weaker still.
RUN useradd --create-home --uid 10001 tapeloop
USER tapeloop
WORKDIR /work

ENTRYPOINT ["tapeloop"]
CMD ["--help"]
