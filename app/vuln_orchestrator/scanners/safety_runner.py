"""Safety dependency vulnerability scanner."""
import subprocess
import json
from typing import Dict, Any, List


def run_safety(requirements_file: str) -> Dict[str, Any]:
    """
    Execute Safety scanner for dependency vulnerabilities.

    Args:
        requirements_file: Path to requirements.txt file

    Returns:
        Safety vulnerability results as dict
    """
    cmd = [
        "safety",
        "check",
        "--file", requirements_file,
        "--json"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # 1 minute max
        )

        # Parse JSON output from stdout
        if result.stdout.strip():
            try:
                safety_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Safety may output non-JSON on errors
                safety_data = []
        else:
            safety_data = []

        return {
            "vulnerabilities": safety_data if isinstance(safety_data, list) else [],
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except subprocess.TimeoutExpired:
        raise Exception("Safety scan timed out after 60 seconds")
    except Exception as e:
        raise Exception(f"Safety execution failed: {str(e)}")
