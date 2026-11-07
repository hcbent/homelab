# Elasticsearch Cluster Manager (ECM)

A self-hosted web app that builds and manages Elasticsearch clusters on Proxmox virtual machines. It reads what is
already running, plans a new cluster with Terraform and Ansible, shows you the plan, and changes nothing until you
approve that exact plan.

**Status as of 2026-11-06: Phase 4 (provisioning) is mostly done.** You can create a three-node cluster from the
browser, watch it build, and tear it down. Everything after that (adding or removing nodes, Kibana, adopting an
existing cluster, upgrades) is planned and not started. This page keeps *works* and *planned* apart on purpose.

## What works

Verified on the lab (Proxmox on `pve1` to `pve3`, ECM on `infra`):

- **Discovery and dashboard, read-only.** ECM reads Proxmox (hosts, VMs, storage, bridges, templates) and
  Elasticsearch clusters you register, links each Elasticsearch node to its VM only on verified evidence, and
  shows both. It never writes to Proxmox or to a discovered cluster.
- **Create a cluster.** The *Create cluster* wizard (single node, three nodes, or three dedicated masters plus
  data and coordinating nodes) checks the plan with a dry run, then makes a plan you approve on the operation page.
  Approving builds the VMs with Terraform and installs, secures and starts Elasticsearch with Ansible. `lab-c`
  (through the terminal helper) and `lab-d` (through the wizard) were built this way and came up green, three nodes
  each, with the master-eligible nodes on different Proxmox hosts.
- **Tear a cluster down.** Done through the terminal helper (`lab-c`) and through the *Tear down cluster* button
  on the cluster page (the first `lab-d`, whose machines were destroyed). That teardown left ECM's record of the
  cluster in the list; a later change, below, makes a teardown remove it.

Also run live on 2026-11-06: a seven-node `lab-d` (three dedicated masters, three data nodes, one coordinating
node) built through the wizard after its dry run, with Terraform limited to two operations at a time because ten
at once timed out on Proxmox's storage lock; and a build whose configure step failed on one node, then finished
green on the same machines when it was retried. Tearing that cluster down from its page removed it from the list
by itself (the operator's report). On a three-node test cluster, the *Grow data disks* panel took the data disks from
100 to 150 GB, and Elasticsearch then reported the larger filesystems.

Built and tested with fakes, **not yet confirmed on the real infrastructure**: marking and checking which
VMs ECM created (`tf_managed`), the installable-version filter, the master quorum rule that refuses a placement,
a retry after a failed *apply*, and the two warnings about a Terraform token that reaches beyond its pool. The
details and the honest limits of each are in [docs/DECISIONS.md](docs/DECISIONS.md).

## What is planned, not built

| Phase | Scope |
|---|---|
| Rest of 4 | A live pass over the unverified items above, per-node overrides and a custom topology in the wizard, a custom Proxmox CA for Terraform |
| 5 Lifecycle | **Started:** growing data disks has run on a real test cluster (100 to 150 GB). *Resize nodes* plans a new CPU and RAM size, has Terraform apply it, and restarts the nodes one at a time (masters last, waiting for green between nodes); run once on a real three-node test cluster (CPU and RAM, 2026-11-07). *Add nodes* adds one or more nodes of one kind with roles you choose, built and tested offline and not yet run on a real cluster. Not started: removing a node, recovery |
| 6 Kibana | Optional Kibana at create time and later, with TLS and a Caddy example |
| 7 Adoption | Bring a discovered cluster under management, only through a zero-diff import |
| 8 Upgrades and hardening | Rolling upgrades (the upgrade-path rules exist, the procedure does not), drift detection, the full doc set |

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for each phase's acceptance criteria.

## Using it

1. Sign in. The *Clusters* page lists every registered cluster with its health, nodes and linked VMs.
   *Infrastructure* holds the Proxmox and Elasticsearch connections, the inventory and the network profiles.
2. **Create cluster** (on the Clusters page): name, version, topology, sizes, then the Proxmox choices. The Review
   step runs a dry run and shows where each node would go and what Terraform would do. *Plan the build* makes a plan
   and opens its operation page.
3. On the operation page, check the plan and its digest, then **Approve and build**. The steps, the plan and the
   redacted log update as it runs. A failed build keeps its machines and can be retried.
4. On a managed cluster's page, **Add nodes** plans new nodes (names, hosts and addresses are chosen for you and shown on the
   plan); after you approve it, only the new nodes are configured and started. **Resize nodes** plans new cores and RAM; after you approve it, ECM restarts the nodes
   one at a time, each briefly out of the cluster. **Grow data disks** plans a larger data disk for some or all data nodes (a disk can only
   be grown, never shrunk); you approve the plan on its operation page, and ECM grows the disk, the partition and the
   filesystem without a restart. **Tear down cluster** plans a destroy of the machines ECM made (you type the cluster
   name, then approve the plan). When it finishes, ECM removes its record of the cluster and keeps the history.
5. `scripts/ecm_cli.py --help` does the same from a terminal: `ops`, `create`, `show`, `watch`, `approve`,
   `retry`, `cleanup` and `remove`. It asks for the admin password and never prints it.

Safety rules the code enforces: nothing is applied without approval of the exact plan digest shown; ECM only
destroys machines it created; one operation runs per cluster at a time; secrets are encrypted at rest and redacted
from logs; and ECM never edits your Caddyfile (an example is in `caddy/`).

## Running it

ECM runs as four containers (`postgres`, `api`, `worker`, `web`) plus a one-shot `migrate`. The worker is the only one
that holds Terraform, Ansible and the SSH key.

```bash
cd deploy
cp .env.example .env        # then edit it; every setting is commented
docker compose --env-file .env up -d --build
```

You need at least a master key for encrypting stored credentials, an admin password hash (made with
`python -m app.hashpw` from `backend/`), and the path of the SSH key the worker uses to reach new VMs. The web
container listens on `127.0.0.1:8480`; put your own reverse proxy in front of it, as in `caddy/Caddyfile.example`.
The worker image is built for the platform you build it on, and the Terraform provider and checksums are pinned in
`backend/Dockerfile`.

## Developing

```bash
# backend (Python 3.12)
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest          # 616 tests as of 2026-11-06
.venv/bin/ruff check app tests

# frontend (React, TypeScript, Elastic UI)
cd frontend && npm install
npm test -- --run                   # 61 tests as of 2026-11-06
npx tsc --noEmit -p . && npx vite build
```

Tests use fakes and recorded fixtures for Proxmox, Elasticsearch, Terraform and Ansible; the discovery fixtures
refuse any request that is not a GET. Nothing in the test suite touches real infrastructure. Integration tests
against a disposable target are planned (Phase 8) and will refuse to run unless the target is flagged disposable.

## Documents

- [ARCHITECTURE.md](ARCHITECTURE.md): the design, with what is built marked in each section
- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md): the phases and their acceptance criteria
- [docs/DECISIONS.md](docs/DECISIONS.md): the dated log of decisions, live results and corrections
- [docs/REPO_AUDIT.md](docs/REPO_AUDIT.md): what was reused from this repository and what was not
- [infra/ansible/README.md](infra/ansible/README.md): the Ansible roles and playbooks
- [CLAUDE.md](CLAUDE.md): rules and conventions for working on the code

The other documents the plan calls for (DEVELOPMENT, DEPLOYMENT, CONFIGURATION, SECURITY, TROUBLESHOOTING) are
planned for Phase 8 and do not exist yet; this page and `deploy/.env.example` are what stand in for them.
