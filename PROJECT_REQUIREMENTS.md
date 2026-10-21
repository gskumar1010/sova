This folder has the architecture diagram and abstract of what this project is trying to accomplish.
This existing GitHub repo is based off https://github.com/rh-ai-quickstart/secure-agents-with-openshell-kata
which provides a foundation for secure agent deployment with OpenShell and Kata Containers.
Our objective is to build an Enterprise-grade, privacy-first vulnerability scanning platform for sovereign environments.

Requirements

Use https://github.com/visa/visa-vulnerability-agentic-harness and
https://github.com/capitalone/vulnhunter repositories extensively and ONLY modify https://github.com/gskumar1010/sova/tree/main/3-demo , https://github.com/gskumar1010/sova/tree/main/app,
and https://github.com/gskumar1010/sova/tree/main/images
to build a Sovereign Oversight & Vulnerability Agent


For building the user interface, have the input as a git url and the output needs to be a dashboard with vulnerabilities
Probably have the project connect to a vulnerability MCP server
As part of testing, test against Git repo that has some vulnerabilities inside.

Assume that I will be using Gemma model served with Openshift AI that is hosting as a service external to this repo.



Additional details

Enterprise organizations operating under stringent data privacy and compliance guidelines require secure, on-premise code auditing solutions that do not rely on external platforms. The **Sovereign Oversight & Vulnerability Agent** delivers an end-to-end, privacy-first security scanning platform natively deployed on Red Hat OpenShift AI.

### Key Features

- **🔒 Zero Data Leakage**: Complete governance over sensitive codebase security
- **🛡️  Layered Sandboxing**: Dual-layer security with Red Hat Sandboxed Containers (Kata) + OpenShell
- **🤖 Agentic Analysis**: AI-powered vulnerability detection using Gemma model
- **📊 Real-time Dashboard**: Intuitive interface with severity metrics and remediation steps
- **🎯 MCP Integration**: Contextualized findings via Model Context Protocol server
- **⚡ Streamlined Workflow**: Simple Git URL input → Comprehensive security report


The platform consists of three main layers:

1. **User Interface**: Web-based dashboard for Git URL input and vulnerability visualization
2. **Sovereign Environment**: Red Hat OpenShift AI platform with secure execution isolation
3. **Analysis Engine**: AI-powered vulnerability detection with specialized agents


### Prerequisites

- Red Hat OpenShift AI cluster
- Red Hat Sandboxed Containers (Kata Containers) enabled
- OpenShell installed
- Gemma model deployed on OpenShift AI outside this repo
