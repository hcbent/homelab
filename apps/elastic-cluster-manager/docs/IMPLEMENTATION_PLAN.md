# Implementation Plan

Each phase is independently testable. A phase is complete only when its acceptance criteria pass in CI with fakes and fixtures. Nothing runs `terraform apply`, a destructive Ansible playbook, or any Proxmox mutation without explicit approval.

## Milestone 0 — Provider spike (recommended first; about 1–2 days)
On **one disposable VM** (pve host and VMID range chosen by the user):
- Create a clone of the Ubuntu template with `bpg/proxmox`, add a second 256 GB disk on `tank`, set a static IP via cloud-init, then resize the data disk, then `terraform import` the VM into a fresh state and confirm a zero-diff plan.
- Output: a short written findings note and a go or no-go on `bpg`.
- **Accept:** all five operations succeed and are repeatable, or the failures are documented and the fallback (Telmate rc10) is evaluated.
- Needs your approval and a scoped API token before it runs. The spike does mutate Proxmox.

## Phase 2 — Foundation
Compose stack (postgres, api, worker, web), Alembic baseline, login and sessions, encrypted credentials, config loading, Procrastinate with a no-op demo job, audit log.
- **Accept:** `docker compose up` yields a working login. A job survives `docker compose restart worker`. Secrets never appear in logs (redaction test). Unauthenticated calls to any non-health endpoint return 401.

## Phase 3 — Discovery and dashboard (read-only)
Proxmox collector (hosts, VMs, storage, bridges, templates), ES collector and manual registration, correlation, dashboard, cluster detail, refresh intervals.
- **Accept:** against recorded fixtures, es01–es09-style topologies appear correctly with links and confidence. A VM running ES but unlinked stays `unlinked`. The UI separates ES-reported, Proxmox-reported, and desired state. Zero write calls are issued to Proxmox or ES (asserted in tests).

## Phase 4 — Provisioning
Desired-state schema and validation, version catalog (artifacts API), topology presets and roles (default → omit `node.roles`), placement, wizard, Terraform runner with plan, approval, and apply, Ansible roles, bootstrap vs join, health verification, jobs UI, dry-run mode.
- **Accept:** unit tests prove `node.roles` omission, `[]` for coordinating, and `initial_master_nodes` only on first bootstrap. Plan generation is deterministic from fixtures. Dry-run touches nothing. A forced failure mid-job leaves resources intact with logs and a working retry. On a disposable target (with approval) a 3-node cluster reaches green.

## Phase 5 — Lifecycle
Add or remove node, resize, disk expansion, destroy, recovery workflows.

Status as of 2026-11-06: **destroy is done** (the teardown: typed name, `tf_managed` check, audit event). The rest is built in slices on one shared foundation, a `tf.update` operation that changes an existing cluster through the same plan, approval, apply and Ansible converge path as a create. Each slice is committed and tested on its own; none is run on infra until its slice says so.
1. **Foundation and disk expansion.** Record each cluster's current desired state; add `tf.update` (Terraform may create or change, never delete or replace); grow a data disk, then the partition and filesystem, with no restart. Refuses a shrink, a size that is not larger, a node with no data disk and a datastore without room. *Built, with its UI, and run live once on 2026-11-06 (a three-node test cluster, 100 to 150 GB).*
2. **Resize CPU and RAM.** A rolling change one node at a time with a health gate between nodes; heap recomputed. *Design (revision 2, at the operator's direction: Terraform applies, an Ansible playbook does the rolling restart) in `docs/DESIGN_RESIZE.md`. Built, and run live once on 2026-11-07 (a three-node test cluster, all nodes to 8 cores and 16 GiB): the Terraform change, the converge and the rolling restart. The ordering of dedicated roles and the failure paths have not run on a real cluster.*
3. **Add a node.** The next name, role and size, placed by the same rules as a create (the master quorum rule included), joined with the cluster's own CA. *Built (the operator chose roles with a multi-select and several nodes of one kind at a time): `docs/DESIGN_ADD_NODE.md`. Tested offline and run on a real test cluster on 2026-11-07 (two ML-type nodes, then two master-eligible nodes, per the operator's report); one more master was refused by the quorum rule, as designed.*
4. **Remove a node.** Refused on quorum loss, on too little disk left and on the last copy of a primary shard; otherwise the node shutdown API, then Terraform. Needs Elasticsearch write calls, which discovery's read-only clients do not make. *Planned.*
5. **Recovery workflows.** What these are is still to be decided with the operator (candidates: restart one node, re-run a converge, rebuild a node whose VM is lost). *Planned.*
Each slice also needs its UI on the cluster page.
- **Accept:** removal is refused in tested scenarios (quorum loss, insufficient disk, only copy of a shard). Disk shrink is refused. Destroy refuses any VM with `tf_managed=false` and requires typed confirmation, and writes an audit event.

## Phase 6 — Kibana
Optional at create time and as a later operation. Independent sizing and placement, TLS, service token, health check, Caddy example.
- **Accept:** Kibana health check passes on the disposable target. Caddy snippet is generated and the existing Caddyfile is untouched.

## Phase 7 — Adoption
Per ARCHITECTURE §3.
- **Accept:** adoption is blocked unless the import plan is zero-diff. Any plan with delete or replace is rejected (tested). The adopted cluster has config management disabled until opt-in. Ansible check-mode diff is shown first.

## Phase 8 — Upgrades and hardening
Rolling upgrades and restarts, drift detection and reconcile workflow, security review, integration test suite (gated by an explicit `DISPOSABLE_TARGET` env), full docs (README, DEVELOPMENT, DEPLOYMENT, CONFIGURATION, SECURITY, TROUBLESHOOTING).
- **Accept:** unsupported upgrades and downgrades are refused. Drift appears in the UI and is never auto-corrected. Integration tests refuse to run unless the target is explicitly flagged disposable. Backup and restore are demonstrated.
- **Possible enhancements** (raised during live use, not committed to, and not part of the acceptance criteria):
  - **Timestamps on the operation log.** Ansible prints a line only when a host finishes a task, so a step that waits on one slow machine (for example "Wait until SSH answers" with a node still booting) shows no sign of life for minutes, and there is no way to tell how long it has been quiet. Show a time on each log line, and consider a line that says which hosts a task is still waiting for. Each stored log line already has its own insert time (`operation_logs.ts`, returned by the API), so part of this may be a display change; the time Ansible itself reports for each task is not captured today (raised 2026-11-06).

Documentation and tests accompany every phase rather than waiting for phase 8.
