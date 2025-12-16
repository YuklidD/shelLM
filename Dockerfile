FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (if any needed for paramiko/crypto)
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
# Add paramiko to requirements if not present, or install directly
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir paramiko

# Copy application code
COPY core_logic.py .
COPY server.py .
COPY personalitySSH.yml .
COPY env_TEMPLATE .env 
# Note: In production, .env should not be copied; secrets should be injected via K8s secrets

# Expose the SSH port
EXPOSE 2222

# Run the server
CMD ["python", "server.py"]
