# Architecture

Status as of 2026-11-06. Each section says what is built. Legend: **BUILT** = in the code and tested;
**LIVE** = also run on the real lab infrastructure; **PARTLY** = some of it; **PLANNED** = designed only, with no code.
`docs/DECISIONS.md` has the dated log behind every status here, including what was only tested with fakes.

## 1. Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend | React + TS + Vite + Elastic UI (EUI) | Changed from Tailwind + shadcn/ui; see docs/DECISIONS.md |
| API | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic | As specified |
| DB | PostgreSQL 16 | As specified. Also the job queue and the Terraform state backend. |
| Jobs | **Procrastinate** (Postgres-backed), not Celery or RQ | Durable and survives restarts, with retries and no Redis. One fewer service. Per-cluster serialization is enforced by the app (see §5). |
| Provisioning | Terraform with `bpg/proxmox`, both pinned and checksummed in the worker image (the provider spike said go; `spike/FINDINGS.md`) | **LIVE** |
| Config mgmt | Ansible, run as the `ansible-playbook` command by `CliAnsibleRunner` in the worker container (not the `ansible-runner` library) | **LIVE** |
| Secrets | Fernet envelope encryption in Postgres. Master key from an env var or Docker secret. | Never in Git |

Containers (**LIVE**): `web` (serves the SPA and proxies `/api`), `api`, `worker` (has Terraform, Ansible and the SSH client), `postgres`, and a one-shot `migrate`. The web container listens on `127.0.0.1:8480`; a reverse proxy on `infra` points at it. An example snippet is provided in `caddy/` and the existing Caddyfile is never edited.

## 2. Component boundaries (Python packages under `backend/app/`)

As built (**BUILT**):

```
api/           HTTP routes (auth, discovery, network profiles, operations, clusters, versions); no business logic
discovery/     Proxmox + Elasticsearch read-only collectors, correlation (correlate.py), sync
desired/       Desired-state models, validation, topology presets, placement, network allocation, version rules
provisioning/  create.py (plan a create), operation.py (the tf.create and tf.destroy operations), render.py and
               hcl.py (generate the Terraform files), runner.py (the Terraform CLI), workspace.py, plan.py,
               ownership.py (which VMs ECM made), vmid.py
configmgmt/    Ansible: inventory.py (the inventory and variables) and runner.py (the ansible-playbook CLI)
jobs.py        Procrastinate tasks, including the scheduled sync
operations.py  The operation state machine: phases, approval, cancel, retry
crypto.py      Encryption, redaction, credential access (not named "secrets": the parent .gitignore would hide it)
network_profiles.py, audit.py, auth.py, config.py, db.py, models.py   as their names say
```

Not built (**PLANNED**): `es/` (lifecycle procedures: safe node removal, rolling upgrade), a UniFi `network/` adapter,
and the `monitoring/` extension point. Node removal, upgrades and resize live in sections 7 and are Phases 5 and 8.

Rules: `api` calls services only. Services depend on interfaces (`ProxmoxClient`, `ESClient`, `TerraformRunner`, `AnsibleRunner`, `DnsProvider`) so tests inject fakes. Terraform and Ansible are invisible to the frontend. No endpoint returns state files or rendered secrets.

## 3. Ownership model

`clusters.ownership` is one of `discovered | adopted | managed`.

- Only `managed` and `adopted` clusters can have Terraform state. Only they can receive mutating operations.
- Every mutating job checks ownership, resource-level ownership (`vms.tf_managed`), and the cluster lock at the service layer. The API layer is not trusted for this.
- Destroy is allowed only on resources with `tf_managed = true`. Destroy also requires a typed-name confirmation and an audit event.

**Status: PARTLY.** Ownership (`discovered | managed`; `adopted` is Phase 7) is enforced on every Terraform operation, and one
active operation per cluster is enforced by the database (section 5). `vms.tf_managed` is derived from the creates ECM
ran (`provisioning/ownership.py`), set after each Proxmox sync, and checked when a teardown is planned and again
before it applies. It guards teardown only; resize and node removal (Phase 5) will need the same check. The typed
name and an audit event are in place for teardown (**BUILT**; teardown from the button was run on infra once).

### Discovery and correlation (**LIVE**)

1. The Proxmox collector reads nodes, `qemu` VMs, configs, storage, and bridges. It uses a read-only token.
2. The ES collector connects to registered endpoints (manual registration, plus candidate endpoints from VM IPs and a configured port scan list). It reads `_cluster/health`, `_nodes`, `_nodes/stats`, `_cat/shards`, and `_cluster/settings`.
3. Correlation joins an ES node to a VM through **verified evidence only**: node `host`/`ip` matching the VM's guest-agent IPs or cloud-init IP, and matching MACs where available. Each link stores its evidence and a confidence of `verified | probable | unlinked`. A VM that merely contains Elasticsearch is never auto-assigned to a cluster.
4. Cluster identity is the ES `cluster_uuid`, never the cluster name.

### Adoption (**PLANNED**, phase 7)

Adoption is a wizard with a mandatory dry-run:

1. The user selects a discovered cluster, and the app shows its VM links.
2. The app generates a Terraform config from the observed VM config and runs `terraform import` into an isolated state in a scratch workspace.
3. `terraform plan` must show **zero changes** on the observed attributes. Anything else blocks adoption and shows the diff. Attributes the module cannot represent are recorded as `unmanaged_attributes` and ignored via explicit, documented `ignore_changes`.
4. After approval, the state moves to the cluster's real state path and the cluster becomes `adopted`.
5. Ansible is **not** enabled by adoption. A separate "config management" opt-in runs `--check --diff` first. Configuration is never overwritten without a reviewed diff.
6. Nothing in this flow can create, replace, or destroy a VM. Plans containing `delete` or `replace` actions are rejected by the runner.

## 4. Terraform state management

**Status: PARTLY (create and destroy are LIVE).**

- One workspace directory per cluster: `/data/clusters/<cluster_id>/tf/` (**LIVE**). Config is generated from the desired state stored on the operation, so users never edit `.tf` files.
- Backend: **Terraform `pg` backend**, one schema per cluster (`schema_name = tf_<cluster_id>`), which gives native locking with no shared state file (**LIVE**). By default the schemas live in ECM's own database; `ECM_TF_STATE_URL` points them at a separate one. A dry run on a cluster made only for it plans on local state instead and leaves no schema (**BUILT**). The nightly `pg_dump` as the backup is not set up by ECM.
- Defence in depth: after every apply or import, the worker also stores an encrypted state snapshot row (`tf_state_snapshots`). **PLANNED**; no such table exists.
- Operation types are distinct job kinds. **BUILT:** `tf.create`, `tf.destroy` and `tf.update` (a change to a built cluster: it may create or change resources, never delete or replace them, and it ends with an Ansible converge; the only change built so far is growing data disks, run on infra once, 100 to 150 GB on a three-node cluster). **PLANNED:** `tf.import`. Each runs `render, init, plan`, stores the plan file and a JSON summary, waits for approval of that plan's digest, then applies that exact saved plan (a create then runs a `configure` step with Ansible). A dry run stops after the plan and cannot be approved.
- `-lock-timeout` is set on plan and apply (**BUILT**). A force-unlock action in the UI is **PLANNED**.
- A failed apply never triggers automatic destroy. Partial state is retained, the logs and the plan are stored, and the operation page offers Retry, which re-plans and needs a new approval (**BUILT**; a retry after a failed *configure* has run live and finished a green cluster, while a retry after a failed *apply* has only run against fakes).

## 5. Jobs and locking

**Status: LIVE**, apart from cancellation.

- `operations` table = source of truth for the UI (phases, status, logs). Procrastinate handles delivery and retries.
- Conflict prevention: partial unique index `uq_operations_one_active_per_cluster` on `operations(cluster_id)` where `state IN ('pending_approval','running')`. This guarantees one active mutating operation per cluster at the DB level. Read-only syncs are exempt.
- Phases are persisted before and after each step. On worker restart, a running operation resumes at its last unfinished phase. Each phase must be idempotent, so a re-run after a crash is safe.
- Cancellation is **PARTLY** built, and simpler than designed: an operation can be cancelled only while it waits for approval, when nothing is running. Cancelling a running operation, at a phase boundary, is **PLANNED**.
- Progress is derived from real phase completion, not timers.

## 6. Ansible design

**Status: LIVE for create.** Clean-room roles, idempotent, with no action dispatcher. **Built:** `os_base`, `data_disk`, `es_package`, `es_tls`,
`es_node` and `es_bootstrap`, with the playbooks `create.yml` and `converge.yml` (`infra/ansible/README.md`). **PLANNED:** the `kibana`
role (Phase 6). `create.yml` has built the three-node `lab-b`, `lab-c` and `lab-d` clusters and a seven-node `lab-d` (three masters, three data nodes, one coordinating node). A node whose SSH drops while cloud-init is still running is waited for and asked again (`wait_for_first_boot.yml`; tested offline with real Ansible against a stand-in for ssh, not yet run live); until that ran live, a retry finished the job.

- Inventory is generated from the DB into a temp directory (mode 0700) for each run, and deleted afterwards.
- `node.roles` is **omitted** when the node's role mode is `default`. It is `[]` for coordinating-only, and it is an explicit list only in `custom` mode.
- `cluster.initial_master_nodes` is rendered only when the job is `create` and the cluster has no `bootstrapped_at` timestamp. It is stripped on later runs. After first successful health check the app sets `bootstrapped_at`.
- TLS: a cluster CA is generated once with `elasticsearch-certutil`. The CA lives in encrypted storage and is distributed to nodes. Joins use the verified CA, not enrollment tokens, and `validate_certs` is never disabled.
- Data disk: the device is addressed by its `/dev/disk/by-id` path (not `/dev/sdb`), formatted only if it has no filesystem, and mounted by UUID (**BUILT**). After Terraform enlarges the disk, the role grows the partition (`growpart`) and the filesystem (`resize2fs` or `xfs_growfs`) of a disk it already recognises, and the API refuses a shrink (**LIVE** once: a three-node cluster's data disks went from 100 to 150 GB and Elasticsearch then reported the larger filesystems; growing an xfs filesystem has not been tried).
- Version-aware install pins the apt package to the exact version. Settings that differ per major version live in version-keyed templates.
- A cluster is reported successful only when health checks pass (expected node count joined, status green, or yellow for single-node dev) (**LIVE**). It can read yellow for a short while after a create and settle to green by itself, as `lab-d` did.

## 7. Lifecycle procedures (`es/`)

**Status: PLANNED, with some pieces built.** Disk growth is built and has run on infra once (section 6); resize (Terraform changes CPU and RAM, then a playbook restarts the nodes one at a time) is built and tested offline, with only its Terraform step run on infra; adding and removing a node and recovery are not. What exists: the upgrade-path rules in
`desired/versions.py` (`check_upgrade`: refuses downgrades, same-version upgrades and skipped majors, and enforces the
latest-minor rule), which no operation calls yet; and placement (below).

- **Remove node:** refuse if removing it breaks the master quorum, if it is the last holder of a primary shard copy, or if the remaining disk cannot absorb its data (watermarks included). Otherwise use the node shutdown API (`PUT _nodes/<id>/shutdown`, type `remove`), wait for completion, then `tf.update`. Master and data nodes are checked separately.
- **Upgrade:** rolling, one node at a time, using the official upgrade-path rules (e.g. 8.19 → 9.x). The app checks the prerequisites (latest minor on the previous major, deprecation API clean). Downgrades are refused. The sequence is: health gate → node shutdown API → upgrade → rejoin → health gate.
- **Resize:** CPU and RAM change via Terraform (with a reboot step orchestrated one node at a time). Heap is recomputed (≤50% of RAM and ≤ ~31 GB) unless it was set manually.
- **Placement (BUILT):** a scoring function over free CPU, RAM and storage per host, using the last Proxmox sync. Master-eligible nodes are spread across hosts as a rule, not a recommendation: a host may hold at most `(master-eligible nodes - 1) // 2` of them, so losing one host keeps the quorum, and a plan that cannot meet it is refused with the reason. A node can be pinned to a host.

## 8. Networking

**Status: BUILT and LIVE** for profiles and allocation; the UniFi adapter is **PLANNED**.

- Network profiles (bridge, VLAN, CIDR, gateway, DNS, search domain, allocation range) are stored and editable.
- IP assignment is static via cloud-init. Duplicate checks run against (a) the app DB and (b) Proxmox VM configs and guest-agent IPs (**BUILT**), and (c) UniFi if configured (**PLANNED**). **Ping and ARP results are never used as proof of availability**. They are shown only as an extra warning.
- UniFi integration is an optional adapter (`DnsProvider`). v1 ships with the manual workflow (the UI shows the DNS records and reservations to create) and a stub interface. DNS creation is a separate retryable job.

## 9. Security

**Status: BUILT** except where marked. Session-cookie login with a single admin (Argon2id) and a CSRF header check. A `users` table with a role exists to allow future RBAC. Proxmox uses API tokens: a read-only one for discovery and, optionally, a second, narrower one for Terraform, with warnings when a Terraform token reaches beyond its pool. ES uses API keys; the `elastic` password is used once to bootstrap and then deleted. Stored credentials are encrypted. A redaction filter runs over subprocess output and operation logs before they are stored. An `audit_events` table records logins and logouts, adding or changing a cluster, connection, credential or network profile, removing a cluster, and every operation's start, approval, cancellation and retry. Containers run as a non-root user, and the worker is the only container with Terraform, Ansible and the SSH key.

**Differs from the original design:** SSH does not use a keypair generated per install. The operator chose one existing key (`~/.ssh/github_rsa`), which the worker mounts read-only as a copy owned by its own user (`ECM_SSH_KEY_FILE`; `docs/DECISIONS.md` has why a copy and not an ACL). The audit table is written only by insert in the code, but nothing in the database enforces that.

## 10. Data model (SQLAlchemy / Postgres)

**Built** (**LIVE**; migrations `0001` to `0006`):

```
users, sessions
credentials               encrypted secrets by kind (Proxmox tokens, Elasticsearch API key and CA key, the one-time elastic password)
proxmox_connections       a Proxmox API endpoint, its discovery token and optional Terraform token
pve_nodes, pve_storages   what the last Proxmox sync saw
vms                       Proxmox VMs, with tf_managed (true only for machines a create of ECM's made)
clusters                  name, ownership, Elasticsearch uuid and version, endpoints, TLS, bootstrapped_at, last snapshot
es_nodes                  nodes of a cluster as Elasticsearch reported them, with the VM link and its evidence and confidence
network_profiles
operations                kind, state, phase, params (the desired state, placement, addresses, VMIDs), plan digest and summary,
                          approval, result, parent operation; a partial unique index allows one active operation per cluster
operation_steps, operation_logs   (logs are redacted before insert)
audit_events
```

The design's other tables are **PLANNED** and do not exist: `kibana_instances` (Phase 6), `observations` and
`drift_findings` (Phase 8; the last sync's snapshot is kept on `clusters` meanwhile), `tf_state_snapshots`, `dns_records`,
and `ip_allocations` (addresses are chosen at planning time, checked against the inventory and recorded in the
operation's parameters, with no table of their own). The design's `vm_links` is `es_nodes.link_*`, and `desired_state`
lives in the create operation's parameters, not on `clusters`.

The three-way comparison (intent, reported, Terraform state) is **PLANNED** (Phase 8). Today the UI keeps what Elasticsearch reported and what Proxmox reported apart and shows them side by side; the intent of a cluster ECM built is in its create operation.

## 11. Repo layout

```
apps/elastic-cluster-manager/
  README.md  ARCHITECTURE.md  CLAUDE.md  docs/
  backend/{app/…, alembic/, tests/ (with tests/fixtures), Dockerfile}
  frontend/{src/…, public/fonts}
  infra/ansible/{roles, playbooks}          (the Terraform files are generated by backend/app/provisioning, not kept here)
  deploy/{docker-compose.yml, .env.example}
  caddy/Caddyfile.example
  scripts/ecm_cli.py
  spike/                                    the provider spike (spike/FINDINGS.md)
```

Integration tests (`tests/integration/`) are **PLANNED** (Phase 8). Nothing refers to the parent repo's paths. Defaults such as `pve1.lab...` come only from `.env` or the settings UI.

## 12. Technical risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | `bpg/proxmox` may not cover a needed feature (clone plus second disk plus static cloud-init, or import fidelity). | Provider spike before building on it. **Closed for create:** the spike said go and creates run live; import fidelity is still open until Phase 7 |
| 2 | Adoption: imported state may show drift on attributes the module doesn't model, which would lead to replacements. | Zero-diff gate, reject any delete or replace action, explicit ignore list |
| 3 | The worker runs Terraform and Ansible with powerful credentials. | Dedicated least-privilege Proxmox role, only the worker holds keys, audit log |
| 4 | Correlating VM to ES node can be ambiguous (multiple NICs, DHCP changes). | Evidence-based links, `probable` links never grant ownership |
| 5 | Resume-after-crash can double-apply a phase. | Idempotent phases, saved plan applied, DB phase markers |
| 6 | Disk expansion with LVM or odd layouts. | Detect the layout first and refuse unknown layouts |
| 7 | Rolling upgrade across 8.19 → 9.x has version-specific gates. | Rules in a data table, tested per version, deprecation API check |
| 8 | Terraform BSL licensing and provider drift. | Pin versions. OpenTofu is an option (see DECISIONS.md). |
| 9 | `terraform` state in Postgres makes Postgres a single point of failure. | Snapshots plus nightly dump, documented restore drill |
| 10 | UniFi API is unofficial and varies by controller version. | Optional adapter, manual fallback ships first |
