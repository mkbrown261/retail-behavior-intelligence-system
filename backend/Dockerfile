FROM python:3.11-slim

# System dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directories
RUN mkdir -p data/snapshots data/clips data/reports

# Copy pre-built frontend into the static/ui directory
# (built by: cd frontend && VITE_API_URL="" npm run build -- --outDir ../backend/static/ui)
# The frontend build is already included in static/ui/

EXPOSE 8000

ENV PORT=8000
ENV DATABASE_URL=sqlite+aiosqlite:///./data/rbis.db
ENV LOCAL_STORAGE_PATH=./data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
