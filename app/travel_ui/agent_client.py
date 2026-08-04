# app/travel_ui/agent_client.py
"""Bridge between the Streamlit UI and the sandboxed OpenCode agent.

Delivers prompts via `openshell sandbox exec -- opencode run`, so every agent
invocation runs under the OpenShell policy proxy inside the Kata VM.
"""
import os
import re
import subprocess
from dataclasses import dataclass

BLOCKED_RE = re.compile(r"policy_denied|blocked|connection refused|denied", re.IGNORECASE)

_FAKE_ITINERARY = (
    "Proposed itinerary:\n"
    "- Flight OA101 (OpenAir) SFO -> BOS, 08:00-16:30, $279\n"
    "- Hotel: Downtown Kata Inn, Boston, $175/night, rating 4.2\n"
    "Trip total (1 night): $454"
)
_FAKE_BLOCKED = (
    "I attempted to follow that instruction, but the outbound request was "
    "blocked by the OpenShell egress policy (policy_denied). Only the travel "
    "service and the model endpoint are allowed, so no data could leave the sandbox."
)


@dataclass
class AgentResult:
    text: str
    egress_blocked: bool
    raw: str


def _looks_like_attack(prompt: str) -> bool:
    p = prompt.lower()
    return any(k in p for k in ("exfiltr", "ignore instructions", "http://evil", "post the env", "curl http"))


def run_agent(prompt: str) -> AgentResult:
    if os.environ.get("TRAVEL_UI_FAKE") == "1":
        if _looks_like_attack(prompt):
            return AgentResult(text=_FAKE_BLOCKED, egress_blocked=True, raw=_FAKE_BLOCKED)
        return AgentResult(text=_FAKE_ITINERARY, egress_blocked=False, raw=_FAKE_ITINERARY)

    sandbox = os.environ.get("SANDBOX_NAME", "opencode-dual")
    timeout = int(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "120"))
    cmd = [
        "openshell", "sandbox", "exec", "-n", sandbox, "--no-tty",
        "--timeout", str(timeout), "--", "opencode", "run", prompt,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    raw = (proc.stdout or "") + (proc.stderr or "")
    blocked = bool(BLOCKED_RE.search(raw))
    text = proc.stdout.strip() if proc.stdout.strip() else raw.strip()
    return AgentResult(text=text, egress_blocked=blocked, raw=raw)
