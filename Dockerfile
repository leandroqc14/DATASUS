# Use a lightweight official Python image
FROM python:3.11-slim

# Avoid writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir jupyterlab

# Create cache directory for downloaded DATASUS files
RUN mkdir -p /app/datasus_cache

# Copy application files (local files like .venv and data cache are ignored via .gitignore)
COPY . /app/

# Expose Jupyter port
EXPOSE 8888

# Start JupyterLab allowing external access and disabling root warnings
# Note: Token is set to empty for ease of use. If exposed publicly, protect it via firewall or reverse proxy.
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
