# Agent API container (src/greenlux_sentinel/api/app.py) -- what infra/modules/container-apps.bicep
# deploys onto Container Apps (docs/ARCHITECTURE.md#azure-service-map). Not used for the ETL
# Functions app -- that has its own, separate deployment path (functions/).

FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 8000

# No reload, no dev flags -- this is the production image. Runs as the image's default (root)
# user; Container Apps doesn't require a non-root user, revisit if this image is ever run
# somewhere that does.
CMD ["uvicorn", "greenlux_sentinel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
