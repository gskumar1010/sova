# Security Model

This document explains the threat model for AI coding agents on shared
clusters and why dual-layer protection (OpenShell + Kata Containers) is
required for defense in depth.

## Threat Model

AI coding agents execute code from natural-language instructions. They run
shell commands, install packages, edit files, and make network requests.
This creates exposure to two distinct threat classes:

### Application-Layer Threats

Prompt injection, data exfiltration, credential theft. An attacker
embeds malicious instructions in untrusted input (a git patch, an issue
comment, a dependency README) that steer the agent toward leaking secrets
or accessing unauthorized services.

These attacks operate through normal application behavior — HTTP requests,
file reads, environment variable access. They do not require any exploit
or vulnerability in the runtime.

### Kernel-Level Threats

Container escape, host filesystem access, lateral movement. The agent
runs code that exploits a vulnerability in the Linux kernel to break out
of the container boundary and access the host or other containers.

Since agents routinely execute `pip install`, `npm install`, `make`, and
arbitrary shell commands, the kernel attack surface is directly exposed.
A compromised dependency can contain kernel exploit code.

## Why Two Layers

### OpenShell: Application-Layer Defense

NVIDIA OpenShell wraps each agent sandbox in a policy-enforced runtime:

- **Network egress proxy** — All outbound connections route through a
  proxy that evaluates destination, port, calling binary, and protocol.
  Default posture is deny-all; only explicitly allowed endpoints pass.
- **Filesystem isolation (Landlock)** — Kernel-enforced read/write
  restrictions on filesystem paths, locked at sandbox creation.
- **Process isolation** — The agent runs as an unprivileged user with
  dropped capabilities.

**Blocks:** Data exfiltration, unauthorized API calls, credential leakage
through network channels.

**Cannot block:** Kernel-level exploits. Landlock and seccomp operate
within the kernel's integrity boundary. If an attacker corrupts kernel
memory, these controls are bypassed entirely.

### Kata Containers: Kernel-Layer Defense

Kata Containers runs each pod inside a lightweight virtual machine with
its own dedicated guest kernel:

- **Separate kernel** — The workload interacts with a guest kernel, not
  the host kernel. Kernel exploits affect only the guest.
- **Hardware-enforced isolation** — The VM boundary is enforced by CPU
  virtualization extensions (VT-x / AMD-V), not by namespaces or cgroups.
- **Memory isolation** — Guest memory (including page cache) is isolated
  from host memory via virtiofs.

**Blocks:** Container escape exploits, kernel privilege escalation,
page-cache corruption, host filesystem access.

**Cannot block:** Application-layer threats. Kata does not inspect network
traffic or enforce egress policies. `curl http://evil/` is a normal
network operation from Kata's perspective.

## Threat Matrix

| Threat | OpenShell | Kata | Both |
|--------|-----------|------|------|
| Data exfiltration via network | Blocks | Allows | Blocks |
| Prompt injection leading to exfiltration | Blocks | Allows | Blocks |
| Credential theft via environment variables | Blocks | Allows | Blocks |
| Container escape via kernel CVE | Allows | Blocks | Blocks |
| Page-cache corruption across containers | Allows | Blocks | Blocks |
| Host filesystem access via /proc | Allows | Blocks | Blocks |

## Case Study: CVE-2026-31431

CVE-2026-31431 is a logic flaw in the Linux kernel's `algif_aead` crypto
subsystem (AF_ALG socket family). It allows an unprivileged process to
obtain a writable reference to a page-cache page belonging to any file on
the same filesystem layer.

**How it works:** The exploit opens an AF_ALG socket with the
`authencesn(hmac(sha256),cbc(aes))` algorithm, uses `splice()` to create
a pipe between a target file's page cache and the socket, then exploits a
reference-counting bug to retain a writable mapping to the page-cache
page after the socket operation completes.

**Why OpenShell cannot block it:** The exploit uses only legitimate
syscalls (`socket`, `bind`, `splice`, `sendmsg`). It does not make any
network connections, access restricted files, or escalate privileges
through the process model. Landlock, seccomp, and `no_new_privs` cannot
prevent kernel memory corruption that happens below their enforcement
layer.

**Why Kata contains it:** Kata uses virtiofs to provide the container
filesystem. Each VM has its own page cache, isolated from the host and
other VMs. Page-cache corruption inside the guest VM is invisible to
other containers and to the host. The exploit "succeeds" (the target file
appears corrupted inside the VM) but the damage cannot escape the VM
boundary.

**Fix:** Kernel commit `a664bf3d603d` (merged April 1, 2026). Patching
the host kernel eliminates this specific vulnerability, but the broader
pattern — kernel bugs that bypass container isolation — is ongoing. Kata
provides structural protection against this entire class.

## Policy Configuration Reference

The OpenShell network policy (`2-deploy/openshell-policy.yaml`) controls
which endpoints the agent can reach. The policy is applied at sandbox
creation time.

### Endpoint allowlist

Each entry specifies a host, port, protocol, and which binaries may
connect:

```yaml
network_policies:
  model_inference:
    name: model-inference
    endpoints:
      - host: your-model-svc.namespace.svc.cluster.local
        port: 8000
        protocol: rest
        enforcement: enforce
        access: read-write
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/bin/python3 }
```

To allow additional endpoints (e.g., a package registry), add another
entry under `network_policies`.

### Filesystem policy

Controls which paths the agent can read and write:

```yaml
filesystem_policy:
  include_workdir: true
  read_only: [/usr, /lib, /proc, /dev/urandom, /etc]
  read_write: [/sandbox, /tmp, /home, /opt, /dev/null]
```

Paths not listed are inaccessible. Landlock enforces these restrictions
at the kernel level.
