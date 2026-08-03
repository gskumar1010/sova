# Design: Travel Booking Business Application Layer

**Date:** 2026-08-03
**Status:** Approved (design phase)

## Background

An external "quickstart checker" evaluated this repository and returned
`NEEDS_IMPROVEMENT` / `MEETS_L1` / `Published: false` (30/50). The core
finding: the repo deploys security infrastructure (Kata + OpenShell around an
OpenCode agent) but ships **no user-facing business application or UI**, which
is a Level 1 gate. Secondary findings: missing Industry tag, no real images in
`docs/images/`, title does not start with an action verb, and the model
endpoint is external/unspecified.

This design adds a **business face** onto the existing dual-protection sandbox
without rearchitecting the security boundary.

## Decisions (locked)

- **Domain:** Travel booking agent (flights + hotels).
- **UI stack:** Streamlit.
- **Model:** Stays external and OpenAI-compatible / model-agnostic. A one-line
  documentation nudge recommends IBM Granite (open-weight) via OpenShift AI as
  the suggested default endpoint — no GPU burden imposed by the quickstart.
- **Mock Travel API:** A real in-cluster network service (not a local dataset),
  so the egress allowlist demonstration is genuine.

## Guiding principle

The security architecture stays the star. OpenCode remains inside the
Kata + OpenShell sandbox, invoked **headlessly via `opencode run`** through
`openshell sandbox exec` (the same supervised-exec path the existing demo uses)
instead of the interactive TUI. Everything new is either a thin presentation
client *outside* the boundary or a tool/allowlist entry *inside* it. "Travel
booking" is achieved by giving OpenCode a travel-search tool + an AGENTS.md
persona, not by introducing a new agent framework.

Runtime wiring note: an earlier draft assumed `opencode serve` (HTTP API) driven
directly by the UI. That would require exposing a sandbox port through the
OpenShell gateway — not a supported OpenShell feature. Using
`openshell sandbox exec -- opencode run "<prompt>"` avoids port exposure, reuses
a proven mechanism, and ensures **every** agent invocation runs under the
OpenShell policy proxy. The gateway is deployed with
`auth.allowUnauthenticatedUsers: true`, so the UI pod reaches the in-cluster
gateway service without JWT plumbing.

Reference: OpenCode headless CLI (`opencode run`) — https://opencode.ai/docs/cli/

## Architecture

```
[ User (browser) ]
        │
        ▼
[ Travel UI pod (Streamlit) ]      ← outside the boundary; presentation only, no shell
        │  openshell sandbox exec -- opencode run "<prompt>"
        ▼
[ OpenShell Gateway ]              ← unauth in this quickstart, lifecycle, policy
        │
        ▼
┌─ Kata VM (hardware isolation, guest kernel) ─────────────┐
│   OpenShell sandbox                                      │
│     • OpenCode agent (opencode run)        ← unchanged   │
│     • travel-search tool → Mock Travel API (ALLOW)       │
│     • egress proxy: model endpoint + Mock Travel API only│
│     • any other egress (exfil attempt)      → DENY       │
└──────────────────────────────────────────────────────────┘
        │ allowed egress
        ▼
[ Mock Travel API pod (FastAPI) ]  ← canned flights/hotels; the allowlisted target
```

### Why the UI sits outside the boundary

The isolated workload is the *risky* one: OpenCode has shell access and executes
untrusted tool calls, so it stays inside Kata + OpenShell. The UI is a thin
client with no shell — it calls OpenCode's HTTP API *through the gateway*. Placing
it outside is correct, not a compromise; the security thesis is untouched.

## Components

| Component | Location | Purpose | New? |
|---|---|---|---|
| Travel UI (Streamlit) | New pod, exposed via Route | Chat → itinerary; visibly surfaces egress DENY | New |
| Mock Travel API (FastAPI) | New pod + Service | Canned flights + hotels; the allowed egress target | New |
| Travel tool + AGENTS.md persona | Inside sandbox (baked into image) | Turns OpenCode into a travel agent | Config change |
| OpenCode headless (`opencode run` via `openshell sandbox exec`) | Inside sandbox | UI delivers prompts under the policy proxy | Config change |
| Egress allowlist entry | OpenShell policy | Allow Mock Travel API service + model; deny all else | Config change |

## Data flow

1. User asks the UI: *"Find a flight to Boston next Tuesday under $300 and a
   hotel near downtown."*
2. UI backend runs `openshell sandbox exec -n opencode-dual -- opencode run "<prompt>"`.
3. OpenCode invokes the travel-search tool, which calls the Mock Travel API.
4. Egress proxy **allows** the Mock Travel API + model endpoint; **denies**
   anything else.
5. Agent composes an itinerary; UI renders it.

## The visible security payoff (two demo paths)

- **Happy path:** flight + hotel request → agent calls the allowlisted API →
  itinerary rendered.
- **Attack path:** a prompt-injection attempt to exfiltrate data to an external
  host → **blocked by OpenShell**, surfaced in the UI. This is the primary
  screenshot for `docs/images/`.

## Repo changes mapped to existing phases

- `app/travel-ui/` — Streamlit source.
- `app/mock-travel-api/` — FastAPI source + canned dataset (flights + hotels).
- `images/travel-ui/Dockerfile`, `images/mock-travel-api/Dockerfile` — new images.
- `images/agent-sandbox/opencode.json` — add travel tool + travel system prompt;
  run in `serve` mode.
- **Phase 2 (`2-deploy/`)** — deploy Travel UI, Mock Travel API + Service, Route;
  extend OpenShell policy allowlist to include the Mock Travel API service.
- **Phase 3 (`3-demo/`)** — demo drives the app: happy path + attack path, and
  retains the Kata guest-kernel isolation check.

## Documentation & evaluator findings closed

| Finding | Resolution |
|---|---|
| No user-facing UI (L1 gate) | Streamlit Travel UI with a Route |
| Title lacks action verb | Retitle → `Deploy Secure AI Travel Agents with OpenShell and Kata on OpenShift` (67 chars; starts with a verb, names OpenShell + Kata + OpenShift). Fallback if a hard length limit is enforced: `Deploy Secure Travel Agents with OpenShell and Kata on OpenShift` (64 chars). No length limit is confirmed — the evaluator reported the old title's length without penalizing it. |
| Missing Industry tag | Add to Tags — proposed `Travel and Transportation` (confirm against official CONTRIBUTING.md taxonomy, not present in this repo) |
| Weak business use case | New README "Business Use Case" section: the travel scenario + audience |
| `docs/images/` only `.gitkeep` | Add rendered architecture diagram (PNG from Mermaid) + UI screenshots incl. blocked-egress moment; reference in README |
| No open-weight model | One-line doc note recommending Granite via OpenShift AI as the default endpoint (code stays agnostic) |
| Low UX | One browser URL + chat box + one-command demo |

## Scope guard (YAGNI)

- Mock API returns a small canned dataset — no real travel integrations.
- No auth beyond what OpenShell/gateway already provide.
- No persistence, no multi-user, no booking-payment flow.
- Just enough for the agent to do something real, useful, and *visible*.

## Open items to confirm during implementation

- Confirm the official Industry taxonomy value (`Travel and Transportation`
  proposed) against the org CONTRIBUTING.md when available.
- Screenshots for `docs/images/` are produced by running the Streamlit UI
  locally in a fake-backend mode (`TRAVEL_UI_FAKE=1`, canned itinerary +
  blocked-egress responses) and capturing with a headless browser — no cluster
  required to generate them.
