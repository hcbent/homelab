# Decisions

## Made (ADR-style, revisable)
1. **Provider:** `bpg/proxmox`, exact-version pinned, subject to Milestone 0.
2. **Queue:** Procrastinate on Postgres, no Redis.
3. **TF state:** `pg` backend, one schema per cluster, plus encrypted snapshots.
4. **Clean-room** Terraform module and Ansible roles. The legacy `tf/modules/proxmox_vm` and `ansible/roles/elasticsearch` are not reused.
5. **Ansible** via `ansible-runner`, with a generated ephemeral inventory.
6. **ES versions** come from `artifacts-api.elastic.co/v1/versions` with a cache. Nothing hardcoded.
7. **Cluster identity** is `cluster_uuid`. VM correlation needs verified evidence.

## Needs your input
1. **Terraform or OpenTofu?** Terraform is installed on this Mac. OpenTofu avoids the BSL license. The recommendation is Terraform for v1, behind a runner interface so it can be swapped.
2. **Proxmox access:** may I create a dedicated API token and role (least privilege), and may I use one disposable VMID range for the Milestone 0 spike? Which VMID range and host?
3. **SSH to Proxmox nodes:** `bpg` needs it for some operations. Acceptable, with a dedicated key?
4. **Template:** the repo references `ubuntu-25.04`. 25.04 is not an LTS release. Should the default be an LTS template such as 24.04, which Elastic supports more clearly?
5. **Addressing:** which VLANs or CIDR and which free range to allocate static IPs from? What does the UniFi controller run (UniFi OS / Network version), and is API access acceptable?
6. **Caddy and web hosting:** how does Caddy reach Docker services on `infra` today (host ports or a shared network), and what hostname should this app have?
7. **Existing es01–es09:** is this a live cluster (the VMIDs 301–309 are in repo scripts) that I should treat as a read-only discovery and adoption target? I will assume yes and read-only.
8. **First-run credentials:** admin password bootstrapping method (env var versus first-run setup page)?
9. **Extraction:** `apps/elastic-cluster-manager` will need its own `.gitignore` and CI later. Fine to defer?
