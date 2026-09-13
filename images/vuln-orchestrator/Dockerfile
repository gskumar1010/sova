# images/vuln-orchestrator/Dockerfile
FROM python:3.11-slim

# Install security scanning tools + git
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /svc

# Install scanning tools first (these are large)
RUN pip install --no-cache-dir \
        semgrep==1.85.0 \
        bandit==1.7.9 \
        safety==3.2.8

# Install app requirements
COPY app/vuln_orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/__init__.py /svc/app/__init__.py
COPY app/vuln_orchestrator /svc/app/vuln_orchestrator

EXPOSE 8080
CMD ["uvicorn", "app.vuln_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
