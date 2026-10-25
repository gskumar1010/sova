"""Semgrep scanner execution and SARIF output generation."""
import subprocess
import json
import tempfile
from typing import Dict, Any, Optional


def run_semgrep(target_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute Semgrep scanner with security rules.

    Args:
        target_path: Path to scan
        output_path: Optional path for SARIF output file

    Returns:
        SARIF formatted results as dict
    """
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.sarif', delete=False) as tmp_file:
        sarif_output = output_path or tmp_file.name

        cmd = [
            "semgrep",
            "--config=p/security-audit",
            "--config=p/secrets",
            "--config=p/owasp-top-ten",
            "--config=p/javascript",
            "--config=p/python",
            "--config=p/dockerfile",
            "--sarif",
            "--metrics=off",
            "--no-git-ignore",
            "--include=*.py",
            "--include=*.js",
            "--include=*.ts",
            "--include=*.yaml",
            "--include=*.yml",
            "--include=*.json",
            "--include=Dockerfile*",
            "--include=*.tf",
            f"--output={sarif_output}",
            target_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )

            # Read the SARIF output
            with open(sarif_output, 'r') as f:
                sarif_data = json.load(f)

            return {
                "sarif": sarif_data,
                "output_file": sarif_output,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        except subprocess.TimeoutExpired:
            raise Exception("Semgrep scan timed out after 300 seconds")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse Semgrep SARIF output: {str(e)}")
        except Exception as e:
            raise Exception(f"Semgrep execution failed: {str(e)}")
