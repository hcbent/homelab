# Adding a node: proposed design (Phase 5, slice 3)

**Status: BUILT on 2026-11-07 with the operator's changes below, and tested offline; it has not been run on a real cluster.** It was written for the operator to review first, because
adding a node changes a live cluster's membership. Items marked *to confirm* have not been checked against this project's
Proxmox, provider or Elasticsearch.

## What is known (read in the code on 2026-11-07)

- **Certificates are issued only to nodes that lack one.** `es_tls` stats each node's certificate and issues only the missing ones,
  signing with the CA passed in as extra vars on the CA host, which is `electable[0]` of the cluster's own nodes. A converge that
  carries the stored CA and a new node therefore issues exactly one certificate and leaves the others alone.
- **A converge never starts a node.** `es_node` enables the service but starts it, and restarts it on a configuration change, only when
  `es_allow_restart` is true, and a converge sets that false for the whole cluster. A new node would be configured and never started.
- **The Terraform module is one instance per node** (`module.node["name"]`), so a new node is a new instance and the plan is "1 to
  add"; a `tf.update` may already create resources but never delete or replace them.
- **Placement** (`recommend_placement`) places every node of a desired state, honouring a node's `pve_node` pin, and enforces the master
  quorum rule (a host may hold at most `(master-eligible nodes - 1) // 2` of them). It charges each placed node on top of the VMs
  already seen on a host, so placing a cluster's existing nodes again would count them twice.
- **Address and VMID allocation** skips what is in use on Proxmox and what is promised to another real create; the promises are read
  from create operations only.
- **Teardown** only lets a destroy delete what the create it belongs to recorded in state, and ownership (`tf_managed`) is derived
  from creates only. Both would treat a node added later as foreign.
- **Waiting for a first boot** is already a playbook (`wait_for_first_boot.yml`) that survives a connection dropping.

## The sequence

The operation is a `tf.update` whose change is `add_node`: `render, init, plan, approval, apply, configure`.

1. **Plan (changes nothing).** The request names a role, sizes, and optionally a Proxmox host. ECM picks the next unused name
   (`<cluster>-NN`, never reusing a number), places the node with the existing nodes pinned to where they are, allocates an
   address and a VMID, and shows all of it on the plan page: name, host, address, VMID, role. The master quorum rule is applied to
   the whole cluster after the addition, and an even number of master-eligible nodes is shown as a warning. **Refused:** a cluster
   that is not green with every node present, no room on any host, a host that would break the quorum rule, a template that
   cannot be read from the chosen host.
2. **Approve, then apply.** Terraform creates the one VM. On a cluster built before the provider's reboot setting, the same plan also
   lists a state-only change on each existing VM; that is expected and harmless.
3. **Configure** runs a new `add_node.yml`, with the stored CA:
   1. wait for the new node's first boot to finish (the existing wait, limited to the new node);
   2. prepare it with `os_base`, `data_disk` and `es_package`, and issue its one certificate;
   3. write `elasticsearch.yml` for every node (the seed list gains the new master-eligible node; on existing nodes this is only a
      pending change, since nothing restarts) and **start only the new node**;
   4. from the worker, with ECM's API key, wait for the node to appear and the cluster to be green with every node present.
   The cluster's desired state gains the node as soon as Terraform has applied it, as for every update.

**A failure** after the VM exists leaves the VM and the new desired state; Retry re-runs the configure, which is safe to repeat.
Abandoning a node that will not join is the remove-node slice's job (or a teardown of the whole cluster).

## What has to be built

- **A per-node "start this one" flag** in the inventory (`es_start_node` on new nodes only), and the `es_node` role starting a
  node, and restarting it on a change, when that flag is set, leaving `es_allow_restart` as it is for everything else.
- **`add_node.yml`**, a worker-side join check role in the style of the rolling restart's, and the wait limited to the new node.
- **Rules** in `lifecycle.py`: the next name, the role and sizes (defaults from the cluster's existing nodes of that role), pinning,
  the quorum rule, and the pre-checks above.
- **Placement without double counting:** the cluster's own VMs are left out of the host view and its nodes pinned, so each is
  charged once.
- **Three fixes to what exists:** allocation reservations also read in-flight `add_node` updates; teardown allows deleting what the
  latest applied operation recorded, not only the create's resources; ownership marking also counts a node an `add_node` update
  made (and stops counting it once its cluster is gone).
- **The API** (`POST /api/clusters/{id}/add-node`) and **the UI**: an "Add a node" panel (role, sizes, optional host) and the
  plan page showing where the node would go.
- **Tests:** the rules and refusals; the operation with fakes (apply, converge request carrying the new-node flag, desired state);
  the three fixes; the playbook against the same kind of fake Elasticsearch as the rolling restart, with the real response shapes;
  and one live run on a disposable cluster, which also answers the *to confirm* items.

## Decisions for the operator

1. **Roles on offer.** *Proposed:* data node, coordinating-only, master-eligible, and all roles, with the form defaulting to the
   same kind as the cluster's data nodes.
2. **A master-eligible addition.** *Proposed:* allowed under the quorum rule, with a warning when the count becomes even. The
   alternative is to refuse any addition that leaves an even number.
3. **What success means.** *Proposed:* the node has joined and the cluster is green. ECM does not wait for shard rebalancing to
   finish, which can take much longer on a big cluster.
4. **How many at once.** *Proposed:* one node per operation (run it again for more), to keep the plan, the placement and a failure
   simple. The alternative is a count, with the same checks across all of them.

## To confirm

- That Elasticsearch adds a joining master-eligible node to the voting configuration by itself (I believe it does, since 7.x; not
  checked here).
- That the new node's VM clone, first boot and join behave like a create's on this Proxmox when the rest of the cluster is busy.
- That `es_ca_host` (the first electable node) is always an existing, reachable node when a node is added.
- The real response shapes of the calls the join check makes, as with the rolling restart: it should stop before changing anything
  if a field is missing rather than guess.

## Risks

- A node that never joins leaves a VM in Terraform's state that ECM cannot yet remove one at a time.
- Rebalancing after a join adds load to a cluster that may already be busy.
- Adding a master-eligible node changes the quorum arithmetic; the rule and the warning are the guard, and they are only as good
  as the placement ECM knows about.

## As built, and where it differs from the proposal

**The operator's answers (2026-11-07):** (1) roles are chosen with a **multi-select dropdown**, not a fixed list; (2) a master-eligible
addition is allowed under the quorum rule with a warning for an even count; (3) success means the node joined and the cluster is
green, not that shards finished rebalancing; (4) **several nodes of one kind can be added at once** (up to 10), one kind per operation.

- **Roles** are one of three modes: Elasticsearch's default roles (every role but `voting_only`), coordinating only (no roles), or a
  chosen set from the 12 valid roles in a multi-select. Sizes left empty are copied from an existing node of the same kind; a data disk
  is offered only when a chosen role holds data.
- **Names** are the next numbers after the highest used, tracked in a `node_counter` that only goes up, so a number is not reused.
- **The master quorum rule bites on a three-host lab.** With three masters on three hosts, adding **one** more master-eligible node
  (including a default-roles node) is refused wherever it goes: four masters allow one per host, so four hosts are needed. Adding **two**
  at once (five masters, at most two per host) is accepted, and so is any number of non-master nodes. The refusal names the host and says why,
  and the panel explains it before you plan.
- **Pre-checks** use the last sync (the cluster was green, and ECM saw every node); the playbook checks again from the worker before it
  starts anything, and stops without starting a node if the cluster is not green with all its existing nodes.
- **Only the new nodes are touched.** `add_node.yml` waits for their first boot, prepares them, issues their certificates with the stored CA
  (existing certificates are left alone), writes their configuration and starts only them (`es_start_node`), then checks from the worker
  that they joined and the cluster is green. Existing nodes are neither configured nor restarted; their seed lists catch up at the next
  converge.
- **The four fixes** to what exists were made first (reservations, teardown safety, ownership marking, placement without double counting),
  each with tests.
- **The plan page** shows a table of where each new node goes (host, address, VM ID, roles, size) and any placement warning.
- **Not built:** a count across mixed kinds, waiting for rebalancing, and removing a node that fails to join (the remove-node slice).
- **Unverified on a real cluster:** all of it. In particular the plays that run on the new machine over SSH (first boot, packages, the
  certificate, the first start) reuse roles a create exercises but have not run for a node joining a live cluster; that Elasticsearch adds
  a new master-eligible node to the voting configuration by itself; that `GET _cluster/health` and `_nodes/os` give what the join check reads
  (the check stops with a message if not); and the clone and boot of the new VM while the cluster is busy.
