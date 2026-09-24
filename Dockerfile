FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY transcriba ./transcriba
COPY samples ./samples
ARG EXTRAS=""
RUN pip install ".${EXTRAS}"
VOLUME ["/data", "/config"]
EXPOSE 8000
ENTRYPOINT ["transcriba"]
CMD ["serve", "-c", "/config/transcriba.yaml", "--host", "0.0.0.0", "--port", "8000"]
