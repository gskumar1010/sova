"""Bandit scanner execution and JSON to SARIF conversion."""
import subprocess
import json
import tempfile
from typing import Dict, Any, Optional


def run_bandit(target_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute Bandit scanner for Python security issues.

    Args:
        target_path: Path to scan
        output_path: Optional path for JSON output file

    Returns:
        Bandit results as dict
    """
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmp_file:
        json_output = output_path or tmp_file.name

        cmd = [
            "bandit",
            "-r",
            target_path,
            "-f", "json",
            "-o", json_output
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )

            # Read the JSON output
            with open(json_output, 'r') as f:
                bandit_data = json.load(f)

            return {
                "results": bandit_data,
                "output_file": json_output,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        except subprocess.TimeoutExpired:
            raise Exception("Bandit scan timed out after 300 seconds")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse Bandit JSON output: {str(e)}")
        except Exception as e:
            raise Exception(f"Bandit execution failed: {str(e)}")
