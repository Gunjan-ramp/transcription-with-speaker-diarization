# Use Microsoft's official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# 1. Install system dependencies
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    xvfb \
    pulseaudio \
    ffmpeg \
    dbus-x11 \
    libasound2 \
    curl \
    gnupg2 \
    unixodbc \
    unixodbc-dev \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Microsoft ODBC Driver 18
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18

WORKDIR /app

# 3. Pre-install browsers
RUN pip install playwright && playwright install chromium

# 4. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt tzdata

# 5. Copy code
COPY . .

# 6. Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
ENV XDG_RUNTIME_DIR=/tmp/pulse-runtime
ENV PULSE_RUNTIME_PATH=/tmp/pulse-runtime

CMD ["/app/entrypoint.sh"]
