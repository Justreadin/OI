FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 1. Install Chromium system dependencies FIRST.
#    This is the layer that was failing with "libatomic.so.1: cannot open shared object file".
#    Every library below is required by Playwright's Chromium on Debian slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    fonts-liberation \
    libatomic1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcb-dri3-0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    wget \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Install Python dependencies. PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD is set above,
#    so pip will not attempt to download Chromium yet.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Install Playwright's Chromium binary now that system libraries exist.
#    This is the step that was failing. It needs libatomic.so.1 which is now installed.
RUN playwright install chromium

# 4. Copy the application.
COPY . .

# 5. Railway injects PORT. Default to 8000 for local runs.
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]