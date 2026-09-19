# renovate: datasource=docker depName=python
ARG PYTHON_VERSION=3.13-slim
FROM python:${PYTHON_VERSION}

LABEL org.opencontainers.image.authors="Rudy van Sloten"
LABEL org.opencontainers.image.url="https://hub.docker.com/r/rdvansloten/terraria-server"
LABEL org.opencontainers.image.documentation="Prometheus exporter for Terraria world and server metrics."
LABEL org.opencontainers.image.source="https://github.com/rdvansloten/terraria-server/blob/main/exporter/Dockerfile"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY terraria_wld.py logs.py metrics.py server.py ./

# Non-root
RUN useradd -u 999 -r -s /bin/false exporter
USER exporter

ENV METRICS_PORT=9150
EXPOSE 9150

ENTRYPOINT ["python", "server.py"]
