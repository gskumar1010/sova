"""Scan lifecycle management with SQLite state persistence."""
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any
import os


class ScanManager:
    """Manages vulnerability scan state and results."""

    def __init__(self, db_path: str = "/tmp/sova_scans.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                scan_id TEXT PRIMARY KEY,
                git_url TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                sarif_path TEXT
            )
        """)
        conn.commit()
        conn.close()

    def create_scan(self, scan_id: str, git_url: str) -> None:
        """Create a new scan record."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO scans (scan_id, git_url, status, started_at) VALUES (?, ?, ?, ?)",
            (scan_id, git_url, "initiated", datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve scan information."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def update_status(self, scan_id: str, status: str) -> None:
        """Update scan status."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        completed_at = datetime.utcnow().isoformat() if status == "completed" else None
        if completed_at:
            cursor.execute(
                "UPDATE scans SET status = ?, completed_at = ? WHERE scan_id = ?",
                (status, completed_at, scan_id)
            )
        else:
            cursor.execute(
                "UPDATE scans SET status = ? WHERE scan_id = ?",
                (status, scan_id)
            )

        conn.commit()
        conn.close()

    def store_sarif(self, scan_id: str, sarif_content: str) -> None:
        """Store SARIF results for a scan."""
        sarif_dir = "/tmp/sova_sarif"
        os.makedirs(sarif_dir, exist_ok=True)

        sarif_path = os.path.join(sarif_dir, f"{scan_id}.sarif")
        with open(sarif_path, 'w') as f:
            f.write(sarif_content)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE scans SET sarif_path = ? WHERE scan_id = ?",
            (sarif_path, scan_id)
        )
        conn.commit()
        conn.close()

    def get_sarif(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve SARIF results for a scan."""
        scan = self.get_scan(scan_id)
        if not scan or not scan.get("sarif_path"):
            return None

        try:
            with open(scan["sarif_path"], 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
