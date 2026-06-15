ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip py3-requests \
    && pip3 install --break-system-packages flask

WORKDIR /app
COPY app/ /app/

ENTRYPOINT ["/usr/bin/python3", "/app/main.py"]
