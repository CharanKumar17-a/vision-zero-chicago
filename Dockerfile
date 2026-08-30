# Vision Zero Chicago - Cloud Run Container Specification
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    VISION_ZERO_DATA_MODE=auto

# Install system dependencies for geospatial libraries (GEOS, GDAL, PROJ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirement files first for optimal layer caching
COPY requirements.txt ./
COPY dashboard/streamlit/requirements.txt ./dashboard/streamlit/

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application and data files
COPY . .

# Expose Streamlit port
EXPOSE 8080

# Run Streamlit with Cloud Run compliant parameters ($PORT, 0.0.0.0, headless)
ENTRYPOINT ["sh", "-c", "streamlit run dashboard/streamlit/app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=false"]
