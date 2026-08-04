# images/travel-ui/Dockerfile
FROM python:3.11-slim

# openshell CLI is required at runtime to reach the sandbox through the gateway.
# Install it from the published release; pin via OPENSHELL_VERSION build arg.
ARG OPENSHELL_VERSION=latest
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# NOTE: replace the following line with the project's official openshell install
# method if a package/binary URL is available. Placeholder install is validated
# in Task 6's deploy step, not here.
RUN curl -fsSL https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh || true

WORKDIR /ui
COPY app/travel_ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/__init__.py /ui/app/__init__.py
COPY app/travel_ui /ui/app/travel_ui

EXPOSE 8501
CMD ["streamlit", "run", "app/travel_ui/app.py", "--server.headless", "true", \
     "--server.port", "8501", "--server.address", "0.0.0.0"]
