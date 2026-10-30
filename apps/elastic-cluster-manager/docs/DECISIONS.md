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
