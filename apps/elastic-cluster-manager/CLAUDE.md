# CLAUDE.md — Elasticsearch Cluster Manager

**Status:** Phase 1 done. Phase 2 (foundation) implemented and unit-tested; compose stack not yet run. Phases 3+ not started. See `ARCHITECTURE.md`, `docs/REPO_AUDIT.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`.

## Rules (hard)
- Never commit secrets. Real env files are gitignored. Commit only `*.example`/`*.template` copies with placeholders. Don't name source files/dirs with `secret`, `token`, or `password` (the parent .gitignore silently ignores them).
- Never run `terraform apply`/`destroy`, infrastructure-changing Ansible, or anything that mutates Proxmox or an existing ES cluster without explicit user approval.
- Never treat the existing es01–es09 cluster or any discovered VM as disposable.
- No secrets in Git. Redact secrets from logs.
- Keep this directory independent of the parent repo: no paths outside `apps/elastic-cluster-manager/`.
- No Kubernetes dependencies. Docker only hosts the management app.
- Distinguish implemented from planned in all docs. Don't report results that weren't produced.

## Conventions
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pytest, ruff. Routes are thin. Logic lives in services behind interfaces (`ProxmoxClient`, `ESClient`, `TerraformRunner`, `AnsibleRunner`, `DnsProvider`).
- Frontend: React + TS strict, Vite, Tailwind, shadcn/ui, Vitest.
- Default ES roles means **omit** `node.roles`. Coordinating-only is `node.roles: []`.
- `cluster.initial_master_nodes` only on the first bootstrap, never after `bootstrapped_at` is set.
- One Terraform state per cluster. Plans containing delete or replace are rejected during adoption.
- Phases must be idempotent so jobs can resume after a restart.
- Tests with fixtures or fakes for Proxmox and ES. Integration tests require an explicit `DISPOSABLE_TARGET`.

## Layout
See ARCHITECTURE.md §11.

## Commands (to be filled in as phases land)
Backend: `cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest`
Frontend: `cd frontend && npm install && npm test`
Deploy: `cd deploy && cp .env.example .env` (edit), then `docker compose --env-file .env up -d --build`
