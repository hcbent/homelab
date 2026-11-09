# ECM Ansible roles

Playbooks and roles that ECM's worker runs against VMs that Terraform created. **Status: written, linted and
checked offline; not yet run on any host.** See `docs/DECISIONS.md` ("Ansible roles, first slice") for what is and
is not verified.

| Playbook | Use |
|---|---|
| `create.yml` | Build a new cluster, once, before `bootstrapped_at` is set. |
| `converge.yml` | Bring an existing cluster's nodes back to the desired config. Run with `--check --diff` first. Never restarts or starts a node. |
| `rolling_restart.yml` | Restart nodes one at a time through Proxmox with the cluster held steady around each. After a resize it restarts the nodes not at their target size; with `es_restart_plan` it follows ECM's plan (named nodes, a stopped VM started, nodes already restarted since the operation began skipped). Needs no SSH. |
| `add_kibana.yml` | Add Kibana to a built cluster (docs/DESIGN_KIBANA.md). Run by the worker after Terraform made the machine: `kibana_credential.yml` first (asks the cluster for the service-account token, or reuses the one ECM holds, and hands a new one back before anything else can fail), then the first-boot wait, then `os_base`, `es_package` (with `es_package_name: kibana`), `es_tls` (for a host that is not a node) and `kibana` on the Kibana machine, then `kibana_health.yml` from the worker. No Elasticsearch node is configured or restarted. |
| `remove_nodes.yml` | Run by the worker twice when nodes are removed: `es_dr_phase: drain` asks Elasticsearch to move every shard off the nodes (node shutdown API) before Terraform destroys them, and cancels and stops if it cannot; `after` waits for green without them. Needs no SSH. |

| Role | Does |
|---|---|
| `os_base` | Base packages including `qemu-guest-agent`, `vm.max_map_count`, swap off, clock check |
| `data_disk` | Partition, format (blank disks only) and mount the data disk by UUID |
| `es_package` | Elastic apt repo with a pinned signing key, exact version, version hold, never starts it |
| `es_tls` | Cluster CA and per-node certificates with `elasticsearch-certutil` |
| `es_node` | `elasticsearch.yml`, heap, first-start keystore entry, start |
| `es_bootstrap` | Waits for the expected nodes and health, makes an API key, hands the result to ECM |
| `kibana_credential` | Worker side: a service-account token for `elastic/kibana` (made once; a retry reuses it; one the cluster has but ECM never received is deleted and made again). Named for the gitignore: the parent `.gitignore` hides anything called `*token*`. |
| `kibana` | `kibana.yml` (HTTPS, explicit Elasticsearch addresses), the keystore (service token and the three encryption keys, by standard input), the service |
| `kibana_health` | Worker side: asks Kibana's `/api/status` with ECM's API key and the cluster CA until `overall.level` is `available`, and fails with what it said |
| `es_drain` | Drains the nodes being removed and checks the cluster afterwards (see `remove_nodes.yml`) |

## Inputs

The inventory comes from `backend/app/configmgmt/inventory.py`. Secrets never go in it: `es_elastic_password`,
`es_ca_cert_pem` and `es_ca_key_pem` are extra vars. The connection uses the SSH key at the path the inventory
names (`github_rsa`); this directory never contains a key.

## Checks that need no VM

```
ansible-galaxy collection install -r requirements.yml
ansible-lint --profile production playbooks roles
cd ../../backend && .venv/bin/python -m pytest tests/test_ansible_inventory.py tests/test_ansible_roles.py
```

`tests/test_ansible_kibana_roles.py` runs `kibana_credential.yml` and `kibana_health.yml` for real against a local HTTPS server that plays
Elasticsearch and Kibana. The roles that run on the Kibana machine (`es_package` for Kibana, `es_tls` there, `kibana`) ran once on a real VM
(2026-11-09, per the operator's log of an Add Kibana on `test-5a`); that is the only live run.

Running a playbook changes real machines. Do it only against VMs you have approved for it.
