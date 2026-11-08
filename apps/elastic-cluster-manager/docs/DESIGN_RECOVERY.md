# Recovery workflows: proposed design (Phase 5, slice 5)

**Status: APPROVED on 2026-11-07 with the operator's answers below (all five proposals accepted except decision 2, where the operator chose to refuse a red cluster); slice 5a is BUILT (backend, join-check gate and UI, tested offline, not run on any cluster); 5b is not built.** The operator left the meaning of "recovery" open (the candidates were restarting a
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

**A red cluster is refused** (a primary shard was only on the lost node, or any primary is unassigned). The message names the unassigned primaries and says their
data is gone unless it is restored from a snapshot. The operator chose this over allowing the rebuild with a warning (decision 2): the data must be dealt with
first, and ECM does not guess. **The consequence is that ECM offers neither rebuild nor forget while a cluster is red**; the operator restores or accepts the
loss by hand (outside ECM), and ECM works again once the cluster is yellow or green.

**Forget** takes a lost node out of the record without destroying anything, for a node that will not be replaced. It is the remove-nodes operation with
two differences for a node that is already gone from Elasticsearch: the green and shards-all-started gates are replaced by "not red" (so a red cluster is refused here too), and the plan
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

- Rules in `lifecycle.py`: `RebuildNodes` and `ForgetNodes`, the lostness check against the last sync, host choice, and the gates (not red); refusals with the reason and
  what it is instead.
- The plan rule: created exactly the named nodes (`check_rebuild_plan`, next to `check_removal_plan`), and the forget rule's state check.
- A `rebuild` flag in the join check's "before" gate (not red instead of green), and `add_node.yml` taking it; `AnsibleRequest` and the inventory carry it.
- Ownership: nothing new (the recreated machine has the VM ID and name the create recorded), but the tests prove it.
- API (`POST /api/clusters/{id}/rebuild-nodes`, `.../forget-nodes`) and a **Recovery** panel listing each node with what ECM sees (machine and Elasticsearch
  node present or not) and the action that fits.
- Tests as for add and remove: every refusal; the plan rules (an empty plan, an extra create, a delete); the gate against the fake Elasticsearch
  (yellow passes, red refuses naming the unassigned primaries, no master refuses); a retry after the apply.

## Decisions for the operator

**The operator's answers (2026-11-07): 1, 3, 4 and 5 as proposed; 2 the refusal.**

1. **Scope and order.** *Proposed:* 5a (rebuild and forget) first, then 5b (restart, including "apply pending configuration"), and re-run converge left to Phase 8.
2. **A red cluster.** *Proposed:* allow a rebuild with a warning that names the unassigned primaries. The alternative is to refuse until the operator has dealt with the data. **The operator chose the refusal**, for rebuild and for forget.
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
- A master rebuilt on a shared host leaves the cluster one host failure from losing its quorum until a host is available to spread them again; the plan's warning says so.
- A rebuilt data node starts empty and pulls its shards from the others, which loads a cluster that is already degraded.
- Forgetting a node whose data was not replicated makes the loss permanent in ECM's record; the red warning and the quorum rules are the guards.

## As built (slice 5a), and where it differs from the proposal

- **The rules** are `plan_rebuild_nodes` and `plan_forget_nodes` in `provisioning/lifecycle.py`, and the plan rules `check_rebuild_plan` and
  `check_forget_plan` in `provisioning/plan.py`. Both recoveries share one live read and its gates (`_recovery_read`): the cluster answers and has
  an elected master, it is **not red** (the refusal names the unassigned primaries and says to restore or accept the loss by hand first, as the operator
  chose), and Elasticsearch reports every node of the record except the ones being recovered. A node is lost only when its machine is absent from
  the last Proxmox sync **and** Elasticsearch does not report it; otherwise the refusal says which it is (a machine that exists is to be started or
  restarted, a VM ID that now belongs to another machine is named, a node the cluster still has is not lost).
- **The forget plan check needs no state read.** The design said the plan rule would accept "nothing to delete" only if the node's resources were out of
  Terraform's refreshed state. The plan itself discriminates: a machine that still exists would show as a delete, so `check_forget_plan` refuses any
  create, delete or replace (a delete of a named node says "use Remove nodes"), and an empty plan is the expected one.
- **A forget always waits for an approval** even though its plan is empty: `_nothing_to_do` (which skips the approval and adopts the parameters when a plan has no
  changes) returns false for `forget_nodes`. The operation then applies the saved empty plan, which Terraform is expected to accept as a no-op
  (*to confirm*), adopts the shrunken record, drops the node's rows, and runs a converge on the remaining nodes. There is no drain and no check afterwards.
- **A rebuild** is a `tf.update` with add-node's phases. Its plan must create exactly the named machines and may not be empty, **except on a retry**
  after this operation's own apply made them (`_already_rebuilt`): then an empty plan is right and the apply is skipped. A failed apply is not mistaken for
  a finished one. The configure step is `add_node.yml` with the rebuilt nodes as the new ones and one new flag (`rebuild`), which makes the join check's gates ask for **yellow
  or better** (`es_jc_min_status`) before and after instead of green. The record's addresses, VM IDs and roles are unchanged; only a moved node's host changes.
- **The host** is one optional choice for every node in the request (as add-node has), else each node's old host if the last sync shows it online, else
  ECM's placement under the master spread rule with every other node pinned where it is.
- **The master spread is a warning for a rebuild, not a refusal (the operator's decision, 2026-11-08).** The first build refused it, and the tests showed
  the consequence: with three masters on three hosts a dead host's master could not be rebuilt on the two left, could not be forgotten (fewer than three masters),
  and add-node refuses while a node is missing, so ECM offered no recovery. The operator's answer: when a host dies, the anti-affinity rule can be ignored in
  favour of getting the cluster back. So `plan_rebuild_nodes` places with `spread_is_required=False`: the placement still spreads where it can, and where it
  cannot (or the operator picks a shared host) the plan page carries a warning that names the host, how many masters it would hold and that losing it would break
  the quorum, and says it is allowed because the cluster is being recovered. Every other rule is unchanged, and forgetting a master is still refused when fewer
  than three would remain.
- **The UI:** a Recovery panel on the cluster page, shown only when a node is lost (machine absent and not in the cluster, from the last syncs), with the nodes
  chosen by default, an optional host, "Plan the rebuild" and "Forget these nodes" (the cluster name typed); a node that has a machine but is not in the cluster
  gets a note that it needs starting or restarting, which is not built. The operation page shows tables for each, a danger-coloured "Approve and forget", and failure
  and success messages that say whether anything was destroyed.
- **Unverified on a real cluster:** all of it. In particular that Terraform's refresh drops a deleted VM from its state so the plan shows a create; that it accepts
  an empty saved plan; that a VM can be created at a VM ID whose disks were left behind on shared storage; that Elasticsearch takes a rebuilt master-eligible node
  (same name, new node ID) into the voting configuration; and that the join steps work on a machine that replaces one of a running cluster's.

## First live result: a rebuild (2026-11-08, the operator's reports and screenshots)

A six-node cluster `test-5a` (three masters, three data and ingest nodes). The operator deleted the VM of `test-5a-05` (VM 504) in Proxmox.

- **Detection needed the Proxmox inventory to be current.** After pressing *Sync now* on the cluster page (which refreshes only Elasticsearch), the cluster was yellow with 2 data nodes but the
  Recovery panel said the node "has a machine in Proxmox but is not in the cluster", because ECM's Proxmox inventory still had the VM's row. After the scheduled Proxmox sync the panel showed
  "1 node is lost: test-5a-05" with the rebuild and forget actions. The stale-inventory problem is in `docs/TODO.md`.
- **Terraform's refresh dropped the deleted VM, as hoped.** The plan was "1 to add, 0 to change, 0 to destroy", and the plan page read "Create 1 virtual machine" with a table row for `test-5a-05`
  (`pve3`, its address, VM 504, `data, ingest`, 4 cores, 8 GiB, 100 GB data) and no warnings. This resolves the first *to confirm* item.
- **The rebuild went through.** The log shows the join check's "before" gate passing, the new machine's first boot, the base packages, the **blank data disk** being partitioned, formatted and
  mounted (the `data_disk` role's blank-disk path), Elasticsearch installed, the certificate issued **only for the new node** (signed on `test-5a-01`, the CA host, with the stored CA), the
  configuration written and the service started and answering, and the join check's "after" gate passing. Recap: `test-5a-05` ok=64 changed=24, the worker's checks ok=9, nothing failed. The
  operation ended "the rebuilt nodes joined and the cluster is not red".
- **Small things:** the join-check task names said "green" while the gate was yellow (renamed); the log window showed only the last 400 of 617 lines, which made the log hard to copy out (a
  "Copy log" button is in `docs/TODO.md`).
- **Not seen yet:** the Terraform apply part of the log (the new VM's creation), what the cluster looked like afterwards and how long it took to return to green, that the node's shards refilled,
  whether the VM really went back to the host in the record (`pve3`; the operator remembered `pve2`), a rebuild of a master with the spread warning, a forget, the refusals (a node whose machine exists,
  a red cluster), and a VM created over disks that were left behind (here the disks were deleted with the VM).

