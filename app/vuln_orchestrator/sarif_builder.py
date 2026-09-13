"""Build SARIF 2.1.0 compliant output from multiple scanning tools."""
import json
from typing import List, Dict, Any, Optional
from datetime import datetime


class SARIFBuilder:
    """Builds SARIF 2.1.0 format vulnerability reports."""

    def __init__(self):
        self.runs = []

    def create_run(self, tool_name: str, tool_version: str = "1.0.0") -> Dict[str, Any]:
        """Create a SARIF run structure for a scanning tool."""
        run = {
            "tool": {
                "driver": {
                    "name": tool_name,
                    "version": tool_version,
                    "informationUri": "https://github.com/gskumar1010/sova"
                }
            },
            "results": []
        }
        self.runs.append(run)
        return run

    def add_result(
        self,
        run: Dict[str, Any],
        rule_id: str,
        level: str,
        message: str,
        file_path: str,
        start_line: int,
        snippet: Optional[str] = None,
        cwe: Optional[str] = None,
        remediation: Optional[str] = None
    ) -> None:
        """Add a vulnerability finding to a run."""
        result = {
            "ruleId": rule_id,
            "level": level,  # error, warning, note
            "message": {"text": message},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": file_path},
                    "region": {"startLine": start_line}
                }
            }]
        }

        if snippet:
            result["locations"][0]["physicalLocation"]["region"]["snippet"] = {"text": snippet}

        if cwe:
            result["properties"] = result.get("properties", {})
            result["properties"]["cwe"] = cwe

        if remediation:
            result["fixes"] = [{
                "description": {"text": remediation}
            }]

        run["results"].append(result)

    def merge_semgrep_sarif(self, semgrep_sarif: Dict[str, Any]) -> None:
        """Merge Semgrep SARIF output into the builder."""
        if "runs" in semgrep_sarif:
            self.runs.extend(semgrep_sarif["runs"])

    def merge_bandit_json(self, bandit_json: Dict[str, Any]) -> None:
        """Convert Bandit JSON output to SARIF and merge."""
        run = self.create_run("Bandit", "1.7.9")

        for result in bandit_json.get("results", []):
            level_map = {
                "HIGH": "error",
                "MEDIUM": "warning",
                "LOW": "note"
            }
            level = level_map.get(result.get("issue_severity", "LOW"), "note")

            self.add_result(
                run=run,
                rule_id=result.get("test_id", "BANDIT-UNKNOWN"),
                level=level,
                message=result.get("issue_text", "Unknown security issue"),
                file_path=result.get("filename", "unknown"),
                start_line=result.get("line_number", 1),
                snippet=result.get("code", None),
                cwe=result.get("issue_cwe", {}).get("id") if isinstance(result.get("issue_cwe"), dict) else None
            )

    def merge_safety_json(self, safety_json: List[Dict[str, Any]]) -> None:
        """Convert Safety JSON output to SARIF and merge."""
        run = self.create_run("Safety", "3.2.8")

        for vuln in safety_json:
            self.add_result(
                run=run,
                rule_id=vuln.get("vulnerability_id", "SAFETY-UNKNOWN"),
                level="error" if vuln.get("severity", "").upper() in ["HIGH", "CRITICAL"] else "warning",
                message=f"Vulnerable dependency: {vuln.get('package_name')} {vuln.get('analyzed_version')}",
                file_path="requirements.txt",
                start_line=1,
                cwe=vuln.get("cve"),
                remediation=f"Update to version {vuln.get('fixed_version', 'latest')}"
            )

    def build(self) -> Dict[str, Any]:
        """Build the final SARIF document."""
        return {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": self.runs
        }

    def to_json(self) -> str:
        """Convert SARIF document to JSON string."""
        return json.dumps(self.build(), indent=2)
