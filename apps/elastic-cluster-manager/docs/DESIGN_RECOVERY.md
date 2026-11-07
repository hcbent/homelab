# Recovery workflows: proposed design (Phase 5, slice 5)

**Status: PROPOSED on 2026-11-07. Nothing here is built.** The operator left the meaning of "recovery" open (the candidates were restarting a
node, re-running a converge and rebuilding a node whose machine is lost), so this proposes a scope and asks for the decisions at the end.
Items marked *to confirm* have not been checked against this project's Proxmox, provider or Elasticsearch.

## What recovery is for

A cluster ECM built has stopped matching its record. Three situations, told apart by what ECM can see (the last Proxmox and Elasticsearch syncs):

| The node's machine in Proxmox | The node in Elasticsearch | What it is | What helps |
|---|---|---|---|
| gone | gone | **Lost** (a host died, a VM was deleted) | rebuild it, or forget it |
| there, stopped | gone | **Down** | start it |
| there, running | gone, or the cluster wants it restarted | **Wedged**, or **config pending** | restart it |

Two things found while testing add and remove make the third row real, not hypothetical:

- **There is no way to restart a node except through a resize.** Every converge after an add or a removal says, for each node, "has not been
  restarted; the change takes effect at the next rolling restart" (the seed lists changed). Nothing offers that restart. The rolling restart picks
  the nodes that are not at their target size, so it restarts nothing when sizes already match.
- **A lost node cannot be removed through ECM, and probably cannot be replaced.** Removal needs a green cluster (a lost node leaves replicas unassigned,
  so the cluster is yellow until Elasticsearch re-replicates, and never if too few data nodes remain), and its plan rule rejects a plan with nothing
  to delete (Terraform's refresh drops a VM that no longer exists from its state, *to confirm*, so the plan has no delete for it). Add-node refuses
  while a node is missing ("ECM saw N of M nodes"). Nothing else rebuilds a machine.

## Proposed scope, in order

### 5a. Rebuild a lost node, and forget a lost node

**Rebuild** puts back a node that is in the cluster's record but whose machine is gone: the same name, address, VM ID and roles, on its old host if
that host is online or on another one if not, with an empty disk, rejoining the cluster. It is add-node for a node that already has a place in the record.

The operation is a `tf.update` whose change is `rebuild_nodes`, with add-node's phases (`render, init, plan, approval, apply, configure`):

1. **Plan (changes nothing).** The request names the lost nodes (and optionally a host for each). ECM checks they are lost (the machine absent from the
   last Proxmox sync, the node absent from Elasticsearch) and refuses if not, saying which it is instead (see the table). The record's parameters do
   not change, except the host of a node moved to another one. Terraform's plan must **create exactly the named nodes' machines** and change
   nothing else (a state-only update on other VMs is allowed, as elsewhere), and must **not be empty**: a plan with no create means the machine
   exists, and running the join steps against a live node would restart it (`es_start_node` restarts on a configuration change). So the plan rule is
   the mirror of the removal rule: every named node created, nothing deleted or replaced.
2. **Approve, then apply.** Terraform makes the machines on the same VM IDs.
3. **Configure** runs `add_node.yml` with the rebuilt nodes as the new ones: wait for first boot, prepare the OS, format the blank data disk
   (the `data_disk` role only ever formats a blank one), issue a certificate with the stored CA (the new machine has none), write the configuration,
   start only those nodes, and check they joined. The one change from add-node is the **health gate**: add-node needs green with every existing node
   first; a rebuild needs only that the cluster answers and **is not red** (it is yellow because of the lost node, and may stay yellow until the
   node is back).

**Refused:** a cluster that cannot elect a master or does not answer (this is quorum loss, recovered by hand, see *Not covered*); a node whose machine
exists; a VM ID that now belongs to a machine ECM did not create (the existing ownership check, which reads the record's VM IDs); a host that cannot take
the node, or that would break the master spread rule (the same placement as add-node, with the other nodes pinned); more lost master-eligible nodes
than the cluster can lose and still have a master.

**A red cluster** (a primary shard was only on the lost node) is allowed with a warning that names the unassigned primaries and says their data is gone
unless restored from a snapshot, because refusing would leave no way to get the node back. See decision 2.

**Forget** takes a lost node out of the record without destroying anything, for a node that will not be replaced. It is the remove-nodes operation with
two differences for a node that is already gone from Elasticsearch: the green and shards-all-started gates are replaced by "not red", and the plan
rule accepts that Terraform has nothing to delete for it, **only if** the node's resources are no longer in Terraform's refreshed state (the plan
alone cannot say, so ECM reads the state's resource list, as it already does after an apply). The quorum and host-spread rules apply as for any
removal. Nothing is drained; there is nothing to drain.

### 5b. Restart nodes

Restart the named nodes, or **every node with a configuration change pending** (the second use is the gap above), one at a time with the rolling
restart's gates: green with every node first, allocation restricted to primaries, flush, restart through Proxmox, wait for the node and for green, masters last, the elected
master last of those. It reuses `rolling_restart.yml` with an explicit list of nodes in place of "not at target size" (one new variable). A node that
is stopped is **started** instead (Proxmox's start call, same right as the restart).

This has no Terraform step, so it needs an operation kind that is not a `tf.*` one: `es.restart` with phases `plan, approval, restart`, where the plan
is the ordered list of nodes and what each will do, and **the digest is over that list** so the approval is still of an exact thing. (An empty Terraform plan skips
approval by design, so a restart must not ride on `tf.update`.) The job, the approval, the retry and the operation page are reused; the handler set is new.

### Not in this slice

- **Re-run a converge.** `converge.yml` already runs inside every update, and a stand-alone "check, show the diff, then apply" is the drift-and-reconcile
  workflow of Phase 8. Building it here would be building that twice. Revisit when Phase 8 starts.
- **Quorum loss, and a lost host with most of the masters on it.** With no master elected the API answers nothing and every ECM check refuses. Recovering
  from it (Elasticsearch's unsafe cluster bootstrap and node repurpose tools) is a manual, destructive procedure that ECM should link to, not run.
- **Restoring data** from a snapshot into a red cluster.

## What has to be built (5a)

- Rules in `lifecycle.py`: `RebuildNodes` and `ForgetNodes`, the lostness check against the last sync, host choice, and the relaxed gates; refusals with the reason and
  what it is instead.
- The plan rule: created exactly the named nodes (`check_rebuild_plan`, next to `check_removal_plan`), and the forget rule's state check.
- A `rebuild` flag in the join check's "before" gate (not red instead of green), and `add_node.yml` taking it; `AnsibleRequest` and the inventory carry it.
- Ownership: nothing new (the recreated machine has the VM ID and name the create recorded), but the tests prove it.
- API (`POST /api/clusters/{id}/rebuild-nodes`, `.../forget-nodes`) and a **Recovery** panel listing each node with what ECM sees (machine and Elasticsearch
  node present or not) and the action that fits.
- Tests as for add and remove: every refusal; the plan rules (an empty plan, an extra create, a delete); the gate against the fake Elasticsearch
  (yellow passes, red passes with the warning, no master refuses); a retry after the apply.

## Decisions for the operator

1. **Scope and order.** *Proposed:* 5a (rebuild and forget) first, then 5b (restart, including "apply pending configuration"), and re-run converge left to Phase 8.
2. **A red cluster.** *Proposed:* allow a rebuild with a warning that names the unassigned primaries. The alternative is to refuse until the operator has dealt with the data.
3. **Where a rebuilt node goes.** *Proposed:* its old host if online, otherwise ECM places it under the master spread rule, and the operator may choose a host. The alternative is its old host only.
4. **Restart as its own operation kind** (`es.restart`) rather than a variant of `tf.update`, so approval cannot be skipped. *Proposed:* yes.
5. **Success for a rebuild.** *Proposed:* the node joined and the cluster is not red, as add-node stops at "joined and green" without waiting for rebalancing. The alternative is to wait for green.

## To confirm

- That Terraform's refresh (the plan runs it by default) drops a VM that was deleted in Proxmox from the state, so the plan shows a create and not an error, with the bpg provider at the pinned version.
- That creating a VM at a VM ID whose disks were left behind (on shared storage, after a host died) works or fails with a message ECM can pass on. The spike once saw an orphaned
  cloud-init volume after a destroy.
- That Elasticsearch reconfigures the voting configuration by itself when a rebuilt master-eligible node (same name, new node ID) joins while its old identity is absent.
- That `GET _cluster/health` answers with a status and a node count on a cluster with a lost node (it does when a master is elected).
- Proxmox's start call and its right (`VM.PowerMgmt`, which a resize already needs).

## Risks

- A mistaken "lost": the last sync is up to a few minutes old, so a node that is only slow could be rebuilt over a live one. The plan rule (the machine must be absent from
  Terraform's refreshed state) and the ownership check are the guards, not the sync.
- A rebuilt data node starts empty and pulls its shards from the others, which loads a cluster that is already degraded.
- Forgetting a node whose data was not replicated makes the loss permanent in ECM's record; the red warning and the quorum rules are the guards.
