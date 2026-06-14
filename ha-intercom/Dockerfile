ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:3.19
FROM ${BUILD_FROM}

ARG GO2RTC_VERSION=1.9.4

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    curl \
    ca-certificates \
    tzdata

# Download go2rtc binary
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        GO2RTC_ARCH="arm64"; \
    else \
        GO2RTC_ARCH="amd64"; \
    fi && \
    curl -fsSL "https://github.com/AlexxIT/go2rtc/releases/download/v${GO2RTC_VERSION}/go2rtc_linux_${GO2RTC_ARCH}" \
        -o /usr/local/bin/go2rtc && \
    chmod +x /usr/local/bin/go2rtc

# Copy Python requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY app/ /app/

# Copy go2rtc base config
COPY go2rtc.yaml /etc/go2rtc.yaml

# Copy run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app

CMD ["/run.sh"]
