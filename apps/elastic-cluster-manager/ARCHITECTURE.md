# Architecture (Proposed — nothing here is implemented yet)

Status legend: **PLANNED** = designed only. Nothing is built.

## 1. Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend | React + TS + Vite + Elastic UI (EUI) | Changed from Tailwind + shadcn/ui; see docs/DECISIONS.md |
| API | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic | As specified |
| DB | PostgreSQL 16 | As specified. Also the job queue and the Terraform state backend. |
| Jobs | **Procrastinate** (Postgres-backed), not Celery or RQ | Durable and survives restarts, with retries and no Redis. One fewer service. Per-cluster serialization is enforced by the app (see §5). |
| Provisioning | Terraform (or OpenTofu, see DECISIONS.md) with `bpg/proxmox`, pinned | |
| Config mgmt | Ansible, run via `ansible-runner` in the worker container | |
| Secrets | Fernet envelope encryption in Postgres. Master key from an env var or Docker secret. | Never in Git |

Containers: `web` (nginx serving the SPA, or Caddy), `api`, `worker` (has terraform, ansible, and ssh), `postgres`. Caddy on `infra` reverse-proxies to `web` and `api`. An example snippet is provided and the existing Caddyfile is never edited.

## 2. Component boundaries (Python packages under `backend/app/`)

```
api/           HTTP routes, auth, schemas (no business logic)
discovery/     Proxmox + Elasticsearch read-only collectors, correlation
desired/       Desired-state models, validation, topology presets, version rules
provisioning/  Terraform runner: render → plan → (approved) apply/import/destroy
config/        Ansible runner: inventory generation, playbook invocation
es/            Elasticsearch REST client + lifecycle procedures (safe removal, upgrades)
jobs/          Procrastinate tasks, operation state machine, locks
crypto.py      Encryption, redaction, credential access (not named "secrets": the parent .gitignore would hide it)
network/       IP allocation/validation, optional UniFi adapter
monitoring/    Empty extension-point interface (v1 has no implementation)
```

Rules: `api` calls services only. Services depend on interfaces (`ProxmoxClient`, `ESClient`, `TerraformRunner`, `AnsibleRunner`, `DnsProvider`) so tests inject fakes. Terraform and Ansible are invisible to the frontend. No endpoint returns state files or rendered secrets.

## 3. Ownership model

`clusters.ownership` is one of `discovered | adopted | managed`.

- Only `managed` and `adopted` clusters can have Terraform state. Only they can receive mutating operations.
- Every mutating job checks ownership, resource-level ownership (`vms.tf_managed`), and the cluster lock at the service layer. The API layer is not trusted for this.
- Destroy is allowed only on resources with `tf_managed = true`. Destroy also requires a typed-name confirmation and an audit event.

### Discovery and correlation (PLANNED)

1. The Proxmox collector reads nodes, `qemu` VMs, configs, storage, and bridges. It uses a read-only token.
2. The ES collector connects to registered endpoints (manual registration, plus candidate endpoints from VM IPs and a configured port scan list). It reads `_cluster/health`, `_nodes`, `_nodes/stats`, `_cat/shards`, and `_cluster/settings`.
3. Correlation joins an ES node to a VM through **verified evidence only**: node `host`/`ip` matching the VM's guest-agent IPs or cloud-init IP, and matching MACs where available. Each link stores its evidence and a confidence of `verified | probable | unlinked`. A VM that merely contains Elasticsearch is never auto-assigned to a cluster.
4. Cluster identity is the ES `cluster_uuid`, never the cluster name.

### Adoption (PLANNED, phase 7)

Adoption is a wizard with a mandatory dry-run:

1. The user selects a discovered cluster, and the app shows its VM links.
2. The app generates a Terraform config from the observed VM config and runs `terraform import` into an isolated state in a scratch workspace.
3. `terraform plan` must show **zero changes** on the observed attributes. Anything else blocks adoption and shows the diff. Attributes the module cannot represent are recorded as `unmanaged_attributes` and ignored via explicit, documented `ignore_changes`.
4. After approval, the state moves to the cluster's real state path and the cluster becomes `adopted`.
5. Ansible is **not** enabled by adoption. A separate "config management" opt-in runs `--check --diff` first. Configuration is never overwritten without a reviewed diff.
6. Nothing in this flow can create, replace, or destroy a VM. Plans containing `delete` or `replace` actions are rejected by the runner.

## 4. Terraform state management

- One workspace directory per cluster: `/data/clusters/<cluster_id>/tf/`. Config is generated from `desired_state` JSON, so users never edit `.tf` files.
- Backend: **Terraform `pg` backend**, one schema per cluster (`schema_name = tf_<cluster_id>`), in a separate `tfstate` database. This gives native locking with no shared state file. The nightly `pg_dump` is the backup.
- Defence in depth: after every apply or import, the worker also stores an encrypted state snapshot row (`tf_state_snapshots`) so recovery does not depend on the DB dump being current.
- Operation types are distinct job kinds: `tf.create`, `tf.update`, `tf.import`, `tf.destroy`. Each runs `plan → store plan file + JSON summary → wait for approval → apply that exact saved plan`.
- `-lock-timeout` is set. A stuck lock is shown in the UI with a force-unlock action that requires confirmation.
- A failed apply never triggers automatic destroy. Partial state is retained, the logs and the plan are stored, and the UI offers "retry apply" and "refresh and re-plan".

## 5. Jobs and locking

- `operations` table = source of truth for the UI (phases, status, logs). Procrastinate handles delivery and retries.
- Conflict prevention: partial unique index on `operations(cluster_id)` where `status IN ('pending_approval','running')`. This guarantees one active mutating operation per cluster at the DB level. Read-only syncs are exempt.
- Phases are persisted before and after each step. On worker restart, a running operation resumes at its last unfinished phase. Each phase must be idempotent, so a re-run after a crash is safe.
- Cancellation is cooperative. It is only honoured at phase boundaries, and never during a `terraform apply` or an ES data migration wait. The UI says "cancel after current step".
- Progress is derived from real phase completion, not timers.

## 6. Ansible design

Clean-room roles (`es_node`, `es_bootstrap`, `kibana`, `os_base`, `data_disk`), idempotent, with no action dispatcher.

- Inventory is generated from the DB into a temp directory (mode 0700) for each run, and deleted afterwards.
- `node.roles` is **omitted** when the node's role mode is `default`. It is `[]` for coordinating-only, and it is an explicit list only in `custom` mode.
- `cluster.initial_master_nodes` is rendered only when the job is `create` and the cluster has no `bootstrapped_at` timestamp. It is stripped on later runs. After first successful health check the app sets `bootstrapped_at`.
- TLS: a cluster CA is generated once with `elasticsearch-certutil`. The CA lives in encrypted storage and is distributed to nodes. Joins use the verified CA, not enrollment tokens, and `validate_certs` is never disabled.
- Data disk: detect the device by serial or ID (not `/dev/sdb`), partition, format only if no filesystem exists, mount by UUID. Expansion runs `growpart` and `resize2fs`/`xfs_growfs` after Terraform enlarges the disk. Shrinking is refused.
- Version-aware install pins the apt package to the exact version. Settings that differ per major version live in version-keyed templates.
- A cluster is reported successful only when health checks pass (expected node count joined, status green, or yellow for single-node dev).

## 7. Lifecycle procedures (`es/`)

- **Remove node:** refuse if removing it breaks the master quorum, if it is the last holder of a primary shard copy, or if the remaining disk cannot absorb its data (watermarks included). Otherwise use the node shutdown API (`PUT _nodes/<id>/shutdown`, type `remove`), wait for completion, then `tf.update`. Master and data nodes are checked separately.
- **Upgrade:** rolling, one node at a time, using the official upgrade-path rules (e.g. 8.19 → 9.x). The app checks the prerequisites (latest minor on the previous major, deprecation API clean). Downgrades are refused. The sequence is: health gate → node shutdown API → upgrade → rejoin → health gate.
- **Resize:** CPU and RAM change via Terraform (with a reboot step orchestrated one node at a time). Heap is recomputed (≤50% of RAM and ≤ ~31 GB) unless it was set manually.
- **Placement:** a scoring function (free CPU and RAM per host, storage, anti-affinity for master-eligible nodes across pve1–3). It uses live Proxmox data and is a recommendation the user can override.

## 8. Networking

- Network profiles (bridge, VLAN, CIDR, gateway, DNS, search domain, allocation range) are stored and editable.
- IP assignment is static via cloud-init. Duplicate checks run against (a) the app DB, (b) Proxmox VM configs and guest-agent IPs, and (c) UniFi if configured. **Ping and ARP results are never used as proof of availability**. They are shown only as an extra warning.
- UniFi integration is an optional adapter (`DnsProvider`). v1 ships with the manual workflow (the UI shows the DNS records and reservations to create) and a stub interface. DNS creation is a separate retryable job.

## 9. Security

Session-cookie login with a single admin (Argon2id) and CSRF protection. Users and roles tables exist from day one to allow future RBAC. Proxmox uses an API token. ES uses API keys, with the `elastic` password used only for initial bootstrap and then discarded. SSH uses a dedicated keypair generated per install. A log redaction filter runs over all subprocess output. An append-only `audit_events` table. Containers run as a non-root user. The worker is the only container with Terraform, Ansible, and SSH keys.

## 10. Data model (SQLAlchemy / Postgres)

```
users(id, username, password_hash, role, created_at)
credentials(id, kind[proxmox_token|es_api_key|ssh_key|unifi|es_elastic], name, ciphertext, key_version, scope_cluster_id?, created_at, rotated_at)
proxmox_clusters(id, name, api_url, credential_id, tls_ca/verify, last_sync_at)
network_profiles(id, name, bridge, vlan, cidr, gateway, dns[], search_domain, range_start, range_end)
clusters(id, name, es_cluster_uuid UNIQUE NULL, ownership, es_version, topology_preset,
         es_endpoint_urls[], es_credential_id, bootstrapped_at, monitoring_ref NULL,
         desired_state JSONB, desired_version int, last_sync_at, created_at)
nodes(id, cluster_id, name, es_node_id NULL, vm_id NULL, roles_mode[default|coordinating|custom], roles[], heap_mb NULL, extra_settings JSONB, es_version)
vms(id, proxmox_cluster_id, pve_node, vmid, name, config_snapshot JSONB, tf_managed bool, tf_address, observed_at)
vm_links(node_id, vm_id, evidence JSONB, confidence)
ip_allocations(id, cidr_profile_id, address UNIQUE, owner_type, owner_id, status[reserved|assigned|released], source)
kibana_instances(id, cluster_id, vm_id, version, resources JSONB, status)
observations(id, cluster_id, source[es|proxmox|terraform], captured_at, data JSONB)    -- reported state
drift_findings(id, cluster_id, scope, path, desired, observed, status[open|accepted|reconciled|ignored], first_seen, last_seen)
operations(id, cluster_id, kind, state, phase, params JSONB, plan_ref, approved_by, approved_at, started_at, finished_at, error, parent_op NULL)
operation_steps(id, operation_id, seq, name, status, started_at, finished_at, detail)
operation_logs(id, operation_id, seq, ts, stream, line)       -- redacted before insert
tf_state_snapshots(id, cluster_id, operation_id, ciphertext, created_at)
dns_records(id, cluster_id, fqdn, address, provider, status, last_error)
audit_events(id, ts, actor, action, target_type, target_id, details JSONB)   -- insert-only
```

The three-way state comparison in the UI uses `desired_state` (intent), `observations` (reported), and Terraform state (read via `terraform show -json`).

## 11. Repo layout

```
apps/elastic-cluster-manager/
  README.md  ARCHITECTURE.md  CLAUDE.md  docs/
  backend/{app/…, alembic/, tests/}
  frontend/{src/…, tests}
  infra/{terraform/modules/es_node, ansible/{roles,playbooks}}
  deploy/{docker-compose.yml, Dockerfile.*, caddy/Caddyfile.example, .env.example}
  tests/{fixtures/{proxmox,elasticsearch}, integration/}
```

Nothing refers to the parent repo's paths. Defaults such as `pve1.lab...` come only from `.env` or the first-run setup UI.

## 12. Technical risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | `bpg/proxmox` may not cover a needed feature (clone plus second disk plus static cloud-init, or import fidelity). | Provider spike before building on it |
| 2 | Adoption: imported state may show drift on attributes the module doesn't model, which would lead to replacements. | Zero-diff gate, reject any delete or replace action, explicit ignore list |
| 3 | The worker runs Terraform and Ansible with powerful credentials. | Dedicated least-privilege Proxmox role, only the worker holds keys, audit log |
| 4 | Correlating VM to ES node can be ambiguous (multiple NICs, DHCP changes). | Evidence-based links, `probable` links never grant ownership |
| 5 | Resume-after-crash can double-apply a phase. | Idempotent phases, saved plan applied, DB phase markers |
| 6 | Disk expansion with LVM or odd layouts. | Detect the layout first and refuse unknown layouts |
| 7 | Rolling upgrade across 8.19 → 9.x has version-specific gates. | Rules in a data table, tested per version, deprecation API check |
| 8 | Terraform BSL licensing and provider drift. | Pin versions. OpenTofu is an option (see DECISIONS.md). |
| 9 | `terraform` state in Postgres makes Postgres a single point of failure. | Snapshots plus nightly dump, documented restore drill |
| 10 | UniFi API is unofficial and varies by controller version. | Optional adapter, manual fallback ships first |
