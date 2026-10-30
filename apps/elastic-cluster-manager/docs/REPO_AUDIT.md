# Phase 1 — Repository Audit

Audit date: 2026-10-30. Scope: `tf/`, `ansible/`, `elasticsearch/`, `docker/`, `docs/`.
Everything here was read from the repo or fetched from upstream. Items marked **UNVERIFIED** were not checked.

## Terraform (`tf/`)

| Finding | Detail | Verdict |
|---|---|---|
| Provider | `telmate/proxmox` pinned to `3.0.2-rc05`. Upstream is at `v3.0.2-rc10` (2026-08-30). Every 3.x release is still a release candidate. | Replace |
| `modules/proxmox_vm` | One boot disk only, no data disk. | Replace |
| | `prevent_destroy = true` plus `ignore_changes` on `disks`, `network`, `ipconfig0`, `sshkeys`, `clone`, and others. Terraform therefore cannot resize, re-IP, or destroy anything. It only tracks VM existence. | Replace |
| | `nameserver`, `searchdomain`, and `ciuser = "bret"` are hardcoded. | Replace |
| Layout | One root per environment (`lab`, `deepfreeze`, `home-apps`, `monitoring`, `kubernetes`, `cchs`). State handling is undefined (no backend block). `kubernetes/` and `k8s_node` are obsolete. | Do not reuse |
| `deepfreeze/import-existing.sh` | Lists `es01`–`es09`, VMIDs 301–309, round-robin over pve1/2/3, imported with ID `<node>/qemu/<vmid>`. | Reuse as discovery fixture and adoption test data. Do not reuse the script. |
| Facts worth keeping | Proxmox host FQDNs are `pveN.lab.thewortmans.org`. The template is named `ubuntu-25.04`. Storage is `tank`. Default bridge is `vmbr0`. Nameserver is `192.168.10.1`. | Seed as configurable defaults only. Never hardcode. |

## Ansible (`ansible/`)

| Finding | Verdict |
|---|---|
| `roles/elasticsearch` uses an "action dispatcher" pattern (`elasticsearch_action: install\|bootstrap\|...`). This is not idempotent by design and is hard to test. | Replace |
| Config is edited with `lineinfile`. Templates enumerate roles explicitly (e.g. `node.roles: [master, data_hot, ...]`). That violates the requirement to omit `node.roles` for "default roles". | Replace |
| `elasticsearch-first-master.yml.j2` sets `xpack.security.enabled: false` on the bootstrap node. | Unacceptable. Security stays on. |
| `cluster.initial_master_nodes` is rendered unconditionally in the first-master template. | Must be bootstrap-only |
| Enrollment-token join flow plus `validate_certs: no` and `es_password` defaulting to `changeme`. | Replace. Use a controlled CA and verified TLS. |
| `domain_suffix`, data paths, and the `/var/lib/elasticsearch` layout are hardcoded. There is no data-disk handling. | Replace |
| Static, hand-edited inventories containing `CHANGEME` credentials. | Replace with a generated inventory |
| Good ideas to carry over: wait-for-green polling, shard-allocation toggling around restarts, and the rolling-restart sequence. | Re-implement cleanly, with tests |
| `roles/kibana` | Not reviewed in depth. Expect a clean-room rewrite for version-aware installs. |
| Other roles (pihole, nut, crowdsec, nginx-lb, docker_apps, fleet) | Out of scope |

## Other

- `ansible/.vault_pass` and `docs/*PASSWORD` exist on disk. Both are gitignored (confirmed with `git check-ignore`). `tf/vault/terraform.tfvars` is also ignored.
- No Caddy config or UniFi tooling exists in the repo. Caddy lives on `infra` outside the repo. The only UniFi mention is in `agent-os/product/mission.md`. Caddy and UniFi details must come from the user.
- `elasticsearch/` holds RAG and ingest scripts for the user's own cluster. It is not provisioning code and is not relevant.
- Repo docs are partly stale (Kubernetes is decommissioned). Nothing in them is treated as truth about the live infrastructure.
- `rhel/` is untracked and unrelated.

## Reuse summary

- **Reuse:** facts and defaults (as configuration), and the es01–es09 inventory as a fixture and adoption candidate.
- **Reuse as ideas only:** the rolling-restart and shard-allocation sequences.
- **Clean-room:** all Terraform modules, all Ansible roles, and the inventory format.

## Provider evaluation (verified 2026-10-30)

| | `bpg/proxmox` | `Telmate/proxmox` |
|---|---|---|
| Latest | v0.119.0 (2026-10-29) | v3.0.2-rc10 (2026-08-30), still RC |
| Cadence | Frequent releases | Slow. rc07 → rc08 gap of about 7 months. |
| API tokens | Supported | Supported |
| Multiple disks, resize, cloud-init, import | Supported (verify in spike) | Historically fragile around disks and cloud-init drift |
| Caveat | Some features (snippets, disk import) need SSH to the node | RC-only |

**Recommendation: `bpg/proxmox`**, pinned to an exact version. The first implementation task is a spike on one disposable VM. The spike covers clone, a second disk, a resize, a static IP via cloud-init, and `terraform import`, before any provider commitment.

## Elasticsearch version metadata (verified)

`https://artifacts-api.elastic.co/v1/versions` returns non-snapshot versions: 8.19.22–24, 9.4.7–9, 9.5.3–6, 9.6.0. The app will read this endpoint, cache it, and filter to stable releases. The latest version is never hardcoded. The `.deb` packages and the apt repo (`artifacts.elastic.co/packages/<major>.x/apt`) are the install source.
