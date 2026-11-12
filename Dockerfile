# One image for the API and the worker; docker-compose.prod.yml picks the command.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app

COPY pyproject.toml README.md ./
COPY packages packages
COPY services services
RUN pip install --no-cache-dir .

COPY migrations migrations
# The compose file ships in the image so the EC2 host always runs the one that matches the code.
COPY alembic.ini docker-compose.prod.yml ./

# The LLM gateway keeps its disk cache in .cache/ under the working directory.
RUN useradd --create-home app && mkdir .cache && chown app .cache
USER app

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
