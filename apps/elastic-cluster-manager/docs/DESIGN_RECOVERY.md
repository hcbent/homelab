# Recovery workflows: proposed design (Phase 5, slice 5)

**Status: APPROVED on 2026-11-07 with the operator's answers below (all five proposals accepted except decision 2, where the operator chose to refuse a red cluster); slice 5a is BUILT and was run on a real cluster (see the live results below); slice 5b (restart nodes) is BUILT, tested offline, not run on any cluster.** The operator left the meaning of "recovery" open (the candidates were restarting a
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

## Second live result: a master rebuilt on a host that already has one (2026-11-08, the operator's screenshots)

The operator deleted the VM of the master `test-5a-01` (pve1, VM 500) and rebuilt it with the host set to `pve2`, which already held `test-5a-03`.

- **The plan page** showed "Create 1 virtual machine" (Terraform: 1 to add, 0 to change, 0 to destroy, plus a change to the *outputs* only, `node_name` of `test-5a-01` going from `pve1` to `pve2`), the
  node's row (`pve2`, its address, VM 500, `master`, 2 cores, 4 GiB) and three warnings: the master spread ("host 'pve2' would hold 2 of 3 master-eligible nodes (test-5a-01, test-5a-03) ... allowed because
  the cluster is being recovered and getting it back matters more"), "test-5a-01 goes to pve2, not pve1 where it was", and a third, older one that says nearly the same as the first (nodes pinned to the same
  host). The operator approved it. So a rebuild that breaks the master spread is accepted with a warning, as decided.
- **The first attempt failed at the first-boot wait.** `cloud-init status --wait` was still running after 900 seconds on the new machine, and the run ended in Ansible's raw "Task failed: Timed out after 900
  second(s)" (the playbook's plain message did not apply to a timeout, which `failed_when` does not cover). The machine was kept. The cause of the slow cloud-init is not known (no console output was seen; the
  other rebuilt node and the original nodes on `pve2` all got through the same wait).
- **Retry worked.** It planned again (nothing to create, since this operation's own apply had made the machine: the retry rule), ran the configure steps again, and the cluster page then showed `test-5a-01` back as
  a master on `pve2`, VM 500, the cluster green with 6 nodes and 6 of 6 VMs linked. The operation page after the retry has not been seen.
- **The voting configuration after the master rebuild** (`GET _cluster/state/metadata?filter_path=metadata.cluster_coordination`, the operator's output): term 2, `last_committed_config` and `last_accepted_config`
  both the same **three** node IDs, and `voting_config_exclusions` empty. Three entries for three master-eligible nodes, nothing pending and nothing excluded, is what a cluster that took the rebuilt master in by itself
  looks like, so the *to confirm* item (a rebuilt master-eligible node, same name and new node ID, joining the voting configuration) holds on this cluster. The three IDs were **not mapped to node names**; matching
  them to `GET _cat/nodes?v&h=id,name,node.role&full_id=true` would rule out a stale entry for the old `test-5a-01` beyond doubt. Term 2 means one election since the cluster formed, consistent with the old
  master having been the elected one.
- **Changed because of it:** the first-boot wait now handles a cloud-init that is still running after its time (`first_boot_cloud_init_wait`, 900 seconds): it is not asked again (that would wait the same
  time again), `cloud-init status --long` and the end of `/var/log/cloud-init-output.log` are put in the log, and the failure says plainly that cloud-init was still running and that Retry is safe.

## Third live result: a forget (2026-11-08, the operator's screenshot)

The operator deleted the VM of the data node `test-5a-05` (VM 504, `pve3`), synced Proxmox, and planned "Forget these nodes".

- **The plan page** said "On Proxmox: Nothing: the machines are already gone", listed the node (`pve3`, its address, VM 504, `data, ingest`), and **waited for approval although the plan was empty**, as designed.
- **It ran to the end in 1m 5s.** All six steps were done, including "Make the changes on Proxmox", which is the **apply of the empty saved plan**: Terraform accepted it, so that assumption holds. The page then said "The lost
  nodes are forgotten ... Nothing was destroyed".
- **The converge touched the five remaining nodes** and restarted none (recap: `test-5a-01` changed=0, `-02` and `-03` changed=1, `-04` and `-06` changed=2, nothing failed). The step is labelled "Install and start
  Elasticsearch" on the page, which is its name for every configure step; for a forget it is a converge and installs nothing. What changed on those nodes was not read from the log (the lines scrolled out of view); the likely
  reason is that this was the first converge since the create, which rewrites `elasticsearch.yml` without `cluster.initial_master_nodes`, a setting that is only ever rendered at the first bootstrap, while `test-5a-01`, written fresh by
  the rebuild, never had it (changed=0).
- **A forgotten data node changes nothing the others refer to**: `discovery.seed_hosts` lists only master-eligible nodes, so for this forget the converge was not needed. Two follow-ups are in `docs/TODO.md`.

## Fourth live result: the refusals (2026-11-08, the operator's console output)

The operator stopped `test-5a-06` (VM 505, a data node) and, with its VM still in ECM's Proxmox inventory, called the two endpoints from the browser console. The cluster page then showed 4 nodes, green, one data node.

- **Both refused with 409 and created no operation.** `rebuild-nodes`: "test-5a-06's machine (VM 505) exists in Proxmox and is running; it is not lost, so it needs to be started or restarted, not rebuilt".
  `forget-nodes`: the same, then "a node whose machine exists is taken out with Remove nodes".
- **"is running" was stale.** The VM had been stopped, but only Elasticsearch was synced (the Proxmox inventory was not), so the message used the VM's last recorded status. The refusal is right either way (the machine exists);
  the status in the text is only as fresh as the last Proxmox sync.
- **A flaw the output showed, now fixed:** the forget message sent the operator to Remove nodes, which cannot take out a node that is down (it needs every node present and green). For a node that is not in the cluster the message now
  says it needs starting or restarting first, that ECM cannot yet start a node, and that Remove nodes cannot take out one that is down.
- **A gap this leaves, for 5b or later:** a node whose machine exists but that will not come back (Elasticsearch will not start, the guest is broken) can be neither rebuilt (the machine exists), forgotten (same), nor removed
  (it is down). Starting or restarting (5b) fixes the usual case. For a machine that cannot be recovered, the way out today is a teardown of the whole cluster; a "remove a down node" workflow (no drain, since there is nothing
  to move, and Terraform destroys the machine and its disks) would close it, and is a decision for the operator.

## As built (slice 5b): restart nodes

- **An operation of its own, with no Terraform.** `es.restart`, phases `plan, approval, restart` (`provisioning/restart.py`, `start_restart` in `operation.py`, dispatched from `run_operation`). It is a separate kind so
  that an empty Terraform plan, which skips the approval by design, can never carry a restart. The plan is made when the operator asks (`plan_restart_nodes` in `lifecycle.py`, from a live read of the cluster) and is the ordered
  list of nodes and what is done to each; **the digest the operator approves is a hash of the cluster and that list**, so what runs is exactly what was approved, and a different plan has a different digest.
- **The request** (`POST /api/clusters/{id}/restart-nodes`) names nodes, or none for every node. **The order** is decided in Python so it can be shown: nodes that are down first (the cluster cannot be green until they are back), then
  coordinating-only, data and master-eligible nodes, the elected master last. **Refused:** a single-node cluster, an unknown node, no elected master, another node being down that is not in the request, a node that is not in the cluster
  and has no machine (it is lost: Recovery), a VM ID that now belongs to another machine, a restart of a node the cluster has when it is red, and when it is yellow with nothing down to explain it. **Warned:** a node that holds the only copy of
  a shard (those indices are unavailable while it restarts) and the elected master.
- **The playbook** is the rolling restart with a new path (`es_restart_plan`; the old size-based path, used after a resize, is unchanged and now lives in `sized.yml`). For each node in the plan it decides **from what is true at that moment**:
  a node the cluster has gets the full treatment (green with every node first, allocation restricted to primaries, flush, a Proxmox reboot, wait for it to rejoin, allocation allowed, green); a node it does not have is **started if its VM is
  stopped and restarted if it runs**, after only checking that the cluster answers. A node that has been **up for less time than the operation has existed** is skipped, which is how a retry resumes without any record of its own (the
  comparison is of two durations, so the clocks of the machines need not agree). A final gate waits for green with every node.
- **A bug the tests found:** Ansible's `now(utc=true)` is a naive UTC time, so `.timestamp()` on it is out by the machine's offset from UTC; on a machine on EST a node looked already restarted. The playbook uses `now()`.
- **Rights:** the pre-flight asks only for `VM.PowerMgmt` on the pool (a new `restarting` flag), and the ownership check covers only the machines in the plan, at the start and again before it runs.
- **Not as designed: "apply pending configuration".** The design also wanted "every node with a configuration change pending". ECM does not know which nodes those are, so the panel offers **Select every node**, which restarts nodes that did not need it.
  Detecting the pending ones is in `docs/TODO.md`.
- **The UI:** a Restart nodes panel (every node with its roles, a note on a node that is down and what will happen to it, a lost node shown but not selectable, Select every node and Clear), and on the operation page the order table with what
  happens to each node, the warnings, "Approve and restart", and messages that say what stays done after a failure.
- **A bug found while testing the panel, not about restarts:** every panel that lists the nodes (Remove, Resize, Grow disks, Recovery) used the bare node name as its checkbox's DOM id, so the ids repeated across panels and a label in a later panel
  toggled the first panel's box. Each panel now prefixes its own (`checkboxIds.ts`), and a test fails if two checkboxes on the page share an id.
- **Unverified on a real cluster:** all of it. In particular that `GET _nodes/stats/jvm?filter_path=nodes.*.name,nodes.*.jvm.uptime_in_millis` returns what the fake does, Proxmox's `status/start` and `status/current` calls and the right they need, a
  start of a node whose VM was stopped, and a restart of a VM that runs while its node is not in the cluster.

## Fifth live result: starting a stopped node with Restart nodes (2026-11-08, the operator's screenshots)

After the three Proxmox hosts were rebooted and ECM redeployed, the operator stopped the VM of `test-5a-06` (VM 505, `pve2`), pressed Sync now, and used the Restart nodes panel.

- **The panel** listed the five nodes and marked `test-5a-06` "(not in the cluster, its machine is stopped: it will be started first)".
- **The plan page** read "What happens: Start 1 node that is down", with a one-row order table: `test-5a-06`, "Started (it is not in the cluster)", `pve2`, VM 505. The sentence under "Then" was awkward for a plan that only starts a node
  ("Restart 1 node one at a time ... goes masters last; test-5a-06 is not in the cluster, so it is brought back first"); it now reads "bring back test-5a-06, which is not in the cluster" and keeps the cautions for plans that restart.
- **It ran to the end in 1m 8s (from creation, approval wait included).** The steps `plan, approval, restart` were done, the final gate waited for green with every node, the old size-based path was skipped, and the recap was ok=27 changed=0
  failed=0. The page said "The nodes are restarted" and the log ended "every node in the plan was restarted and the cluster is green".
- **What this settles:** Proxmox's `status/current` and `status/start` calls and the `VM.PowerMgmt` right work, a stopped node's VM is started and the node rejoins, and `GET _nodes/stats/jvm` answers (the plan's uptime read runs for every node).
- **Not yet seen:** a restart of a node the cluster has (the allocation steps and the reboot through Proxmox), the uptime-based skip on a retry against a real cluster, and "every node" with the masters last.

## Sixth live result: restarting a node the cluster has (2026-11-08, the operator's log)

A restart of the data node `test-5a-04` alone ("1 to restart, 0 to start").

- **Every step ran in the order designed:** the plan assertions, the cluster asked which nodes it has and how long each has been up (the real `uptime_in_millis` field is there and the "already restarted?" decision ran; the node was
  not skipped, correctly), the VM's state read from Proxmox, the **strict green gate** before the node, **allocation restricted to primaries**, the flush, the **Proxmox reboot**, the wait for Proxmox's task (one poll), the wait for the node to join
  (four polls), the yellow gate, **allocation allowed again**, the green gate (one poll) and the final green gate. Recap ok=34, nothing failed or changed. The polls are 10 seconds each, so the node rejoined about 40 to 50 seconds after Proxmox finished.
- **This settles** that `GET _nodes/stats/jvm` with `filter_path` returns the uptime field the retry logic reads, and that a reboot through Proxmox of a node the cluster has works end to end.
- **A misleading label, fixed:** the play was still named "Restart the nodes that are not at their target size, one at a time" (its name from the resize), and the skipped resize path appeared in the log under a similar name. The play is now "Restart nodes one at a
  time, as ECM planned or after a resize", and the resize path says it only runs after a resize.
- **Not yet seen:** a restart of every node (masters last, the elected master last), and a retry that skips nodes already restarted, against a real cluster.

