#!/bin/bash
# Startup script to stage required files to /sandbox/ before OpenCode starts
# This runs on every container start, ensuring files persist across pod restarts

set -e

echo "[startup] Staging files to /sandbox/ workspace..."

# Wait for /sandbox to be mounted (PVC)
timeout=30
while [ ! -d "/sandbox" ] && [ $timeout -gt 0 ]; do
    sleep 1
    timeout=$((timeout - 1))
done

if [ ! -d "/sandbox" ]; then
    echo "[startup] ERROR: /sandbox directory not found after 30s"
    exit 1
fi

# Stage files from image to sandbox workspace
if [ -f "/home/user/workspace/vuln_scan.py" ]; then
    cp -f /home/user/workspace/vuln_scan.py /sandbox/
    chmod +x /sandbox/vuln_scan.py
    echo "[startup] ✓ Staged vuln_scan.py"
fi

if [ -f "/home/user/workspace/SECURITY_ANALYST.md" ]; then
    cp -f /home/user/workspace/SECURITY_ANALYST.md /sandbox/
    echo "[startup] ✓ Staged SECURITY_ANALYST.md"
fi

# Stage persona to .agents/ directory for OpenCode
mkdir -p /sandbox/.agents
if [ -f "/home/user/workspace/SECURITY_ANALYST.md" ]; then
    cp -f /home/user/workspace/SECURITY_ANALYST.md /sandbox/.agents/security-analyst.md
    echo "[startup] ✓ Staged to .agents/security-analyst.md"
fi

echo "[startup] File staging complete"

# Execute original entrypoint with all arguments
# This preserves the OpenShell supervisor startup
exec "$@"
