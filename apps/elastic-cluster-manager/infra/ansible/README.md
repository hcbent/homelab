# ECM Ansible roles

Playbooks and roles that ECM's worker runs against VMs that Terraform created. **Status: written, linted and
checked offline; not yet run on any host.** See `docs/DECISIONS.md` ("Ansible roles, first slice") for what is and
is not verified.

| Playbook | Use |
|---|---|
| `create.yml` | Build a new cluster, once, before `bootstrapped_at` is set. |
| `converge.yml` | Bring an existing cluster's nodes back to the desired config. Run with `--check --diff` first. Never restarts or starts a node. |

| Role | Does |
|---|---|
| `os_base` | Base packages including `qemu-guest-agent`, `vm.max_map_count`, swap off, clock check |
| `data_disk` | Partition, format (blank disks only) and mount the data disk by UUID |
| `es_package` | Elastic apt repo with a pinned signing key, exact version, version hold, never starts it |
| `es_tls` | Cluster CA and per-node certificates with `elasticsearch-certutil` |
| `es_node` | `elasticsearch.yml`, heap, first-start keystore entry, start |
| `es_bootstrap` | Waits for the expected nodes and health, makes an API key, hands the result to ECM |

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

Running a playbook changes real machines. Do it only against VMs you have approved for it.
