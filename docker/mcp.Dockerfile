# Virtual Cell MCP server over Streamable HTTP, behind OAuth (docs/remote_mcp.md).
#
# Separate from docker/Dockerfile, which serves the REST API and is unchanged. This image
# serves the same six MCP tools `python -m virtualcell.mcp` serves over stdio, from the
# same build_server(), for a host that connects by URL.
#
# - Python 3.12, the project floor.
# - `[mcp-http]` only: no `[llm]`, no generation API key. The research tools call no model.
# - Runs as a non-root user.
# - Binds 0.0.0.0 on the platform's PORT (Render sets 10000), one process, one worker:
#   the issued-evidence record is per process, so a second worker would split it.
# - Refuses to start without its OAuth settings (VCRP_MCP_RESOURCE_URL,
#   VCRP_MCP_OAUTH_ISSUER, VCRP_MCP_ALLOWED_SUBJECT, VCRP_MCP_REQUIRED_SCOPES). They are
#   deployment settings, never baked into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install ".[mcp-http]" \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin vcrp

USER vcrp

ENV VCRP_MCP_HOST=0.0.0.0 \
    PORT=10000

EXPOSE 10000

CMD ["python", "-m", "virtualcell.mcp", "--literature", "--transport", "streamable-http"]
