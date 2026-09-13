# images/vuln-ui/Dockerfile
#
# SOVA Vulnerability Dashboard UI (Streamlit). The UI drives the sandboxed
# security agent by shelling out to `openshell sandbox exec ... opencode run`,
# so the openshell CLI must be present in this image.
FROM registry.access.redhat.com/ubi10/ubi:latest

# UBI 10 provides glibc 2.39 (required by the openshell manylinux_2_39 wheel
# published on PyPI) and Python 3.12. Install Python + pip.
RUN dnf -y install python3 python3-pip git \
    && dnf clean all

WORKDIR /ui

# openshell CLI (provides the `openshell` binary + Python client library).
# Installed from PyPI; the x86_64 wheel is manylinux_2_39, hence the UBI 10 base
# (glibc >= 2.39). Pin the version to match the deployed gateway.
ARG OPENSHELL_VERSION=0.0.103
RUN pip3 install --no-cache-dir "openshell==${OPENSHELL_VERSION}" \
    && openshell --version

COPY app/vuln_ui/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/__init__.py /ui/app/__init__.py
COPY app/vuln_ui /ui/app/vuln_ui

EXPOSE 8501
CMD ["streamlit", "run", "app/vuln_ui/app.py", "--server.headless", "true", \
     "--server.port", "8501", "--server.address", "0.0.0.0"]
