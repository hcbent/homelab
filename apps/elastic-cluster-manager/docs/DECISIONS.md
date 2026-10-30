# Decisions

## Made (ADR-style, revisable)
1. **Provider:** `bpg/proxmox`, exact-version pinned, subject to Milestone 0.
2. **Queue:** Procrastinate on Postgres, no Redis.
3. **TF state:** `pg` backend, one schema per cluster, plus encrypted snapshots.
4. **Clean-room** Terraform module and Ansible roles. The legacy `tf/modules/proxmox_vm` and `ansible/roles/elasticsearch` are not reused.
5. **Ansible** via `ansible-runner`, with a generated ephemeral inventory.
6. **ES versions** come from `artifacts-api.elastic.co/v1/versions` with a cache. Nothing hardcoded.
7. **Cluster identity** is `cluster_uuid`. VM correlation needs verified evidence.

## Answered by the user (2026-10-30)
1. **Terraform** (not OpenTofu), behind a runner interface.
2. **Proxmox:** a dedicated token is approved. Disposable VMs use **VMID 5xx**. Host is any pve node. The token itself is still to be provided (not by committing it).
3. **SSH to Proxmox nodes:** approved, with a dedicated key.
4. **Template:** selected by **VMID, default 8000**, as a setting (`ECM_DEFAULT_TEMPLATE_VMID`). `ECM_DEFAULT_TEMPLATE_NAME=ubuntu-25.04` is the fallback. Open question for the spike: confirm 8000 is a template on which node.
5. **Network:** VLAN 10, `192.168.10.0/24`. A DHCP-excluded static range is still to be chosen by the user. UniFi version is still unknown.
6. **Hosting:** Caddy on `infra.lab.thewortmans.org`. The app is `ecm.lab.thewortmans.org`.
7. **es01–es09 is live.** Read-only discovery and adoption target only.
8. **Admin credential:** an Argon2id hash in the `ECM_ADMIN_PASSWORD_HASH` environment variable. This is more secure than a plaintext password variable, and a first-run page would be an open window before setup.
9. **Secrets policy (hard rule):** secrets are never committed. Real env files are gitignored. Only `*.example` or `*.template` copies with placeholders are committed.

## Phase 3 implementation notes
- **Deviation from ARCHITECTURE.md §10:** the VM link lives directly on `es_nodes` (`vm_id`, `link_confidence`, `link_evidence`) instead of a separate `vm_links` table. Simpler, and a node has at most one VM.
- **Proxmox connection:** one row per API endpoint. If pve1–3 form one PVE cluster, a single connection lists all three nodes. If they are standalone, add three connections. To be confirmed on the live system.
- **Correlation** uses the node's published IP against guest-agent IPs and static cloud-init IPs. Guest-agent evidence outranks configuration. MAC addresses are stored but ES does not report them, so they are not used.
- **Stale rows:** VMs, nodes and storage that disappear from a source are deleted from the observed-state tables on the next successful sync.
- **TLS:** verification is on by default. A pasted CA certificate or an explicit "skip verification" opt-in is available, and the opt-in is audited.
- **Fixtures are synthetic** (RFC 5737 addresses, invented names). They follow the real API response shapes but have not been checked against a live Proxmox or Elasticsearch yet.
