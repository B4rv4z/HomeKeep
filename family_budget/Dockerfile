FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_PATH="/data"

WORKDIR /app

# Install OS dependencies (including MuPDF requirements for PDF parsing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmupdf-dev \
    libfreetype6-dev \
    libharfbuzz-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY run.sh ./run.sh
RUN chmod +x ./run.sh

# Create data directory
RUN mkdir -p /data

EXPOSE 8000

VOLUME ["/data"]

CMD ["./run.sh"]
