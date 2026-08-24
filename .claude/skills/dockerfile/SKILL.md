---
name: dockerfile
description: Use when authoring or modifying Dockerfiles. Covers hadolint (static analysis) and trivy (vulnerability + misconfiguration scan). Configs in `${LINT_CONFIGS}/`. Project-specific conventions in `kb/conventions/agents.md` § Container image.
---

# dockerfile

Static analysis (`hadolint`) and security scan (`trivy config` for IaC misconfigurations, `trivy image` for built-image CVEs) for Dockerfiles.

## Files covered

- `**/Dockerfile`
- `**/Dockerfile.*`
- `**/*.Dockerfile`
- `**/Containerfile`

## Linters

### hadolint — Dockerfile static analysis (JSON)

```bash
hadolint -c ${LINT_CONFIGS}/hadolint.yaml --format json <Dockerfile>
```

Returns a JSON array. Each finding has `code` (`DLxxxx` or `SCxxxx` for embedded shell), `level` (`error`/`warning`/`info`/`style`), `file`, `line`, `column`, `message`.

Severity tier mapping:
- `error` → blocker
- `warning` → fix-if-touched
- `info`, `style` → nit

### trivy config — IaC misconfiguration (JSON)

```bash
trivy config --config ${LINT_CONFIGS}/trivy.yaml --format json <Dockerfile-dir-or-file>
```

### trivy image — built-image CVE scan (JSON)

```bash
trivy image --config ${LINT_CONFIGS}/trivy.yaml --format json <image-tag>
```

Config restricts to `HIGH` and `CRITICAL` severities — any finding at those levels is a blocker. `trivy` also has a `secret` scanner; for accidentally-committed credentials the [`secrets` skill](../secrets/SKILL.md) (`gitleaks`) is the authoritative path. `trivy --scanners secret` and `gitleaks` overlap on purpose for defense-in-depth — expect duplicate findings under different rule IDs.

## Per-line inline suppressions

```dockerfile
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends curl
```

Prefer inline over loosening the global config.

## Project-specific conventions

Agent images follow [`kb/conventions/agents.md`](../../../kb/conventions/agents.md) § Container image — the build context is the agent's own directory, dependencies install from the committed `uv.lock`, the final stage runs as a non-root user with a writable `HOME`, and the build fails fast if the bundled `claude` CLI is missing.

## When the executor runs this

After editing any Dockerfile. The [`task-review` agent](../../agents/task-review.md) re-runs `hadolint` and `trivy config` on the diff before commits. `trivy image` only runs when a fresh image tag is available (i.e. after a local `docker build`).
