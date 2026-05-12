# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for suspected vulnerabilities.

Instead, report the issue privately with:

- affected version or commit
- reproduction steps
- impact assessment
- any suggested mitigation

Preferred channels:

1. **GitHub private vulnerability reporting / security advisories** on the published repository
2. **Email:** `Aaron.Tzeng@gmail.com`

Please include `[cc-duet security]` in the subject line when reporting by email.

## Supported versions

- `0.3.x`: supported
- older versions: best effort only

## Scope notes

This project scaffolds a target-project sidecar that intentionally runs AI-generated commands through Codex in a sandboxed workspace. The main security boundaries are:

- Codex native sandboxing (`workspace-write`)
- explicit env-var allowlists
- queue state audit trail in git
- Claude review before completion

Known limitations:

- network egress is not separately firewalled by this project
- secret scanning is regex-based and may have false positives/negatives
- Windows is not currently supported
