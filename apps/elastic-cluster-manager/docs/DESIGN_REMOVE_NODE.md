# Removing nodes: proposed design (Phase 5, slice 4)

**Status: PROPOSED on 2026-11-07. Nothing here is built.** It is written for the operator to review first, because removing a
node destroys a machine and its data disk, and a mistake can lose data or the cluster's quorum. Items marked *to confirm* have not
been checked against this project's Proxmox, provider or Elasticsearch. Recovery workflows (slice 5) are not covered here.

## What is known (read in the code on 2026-11-07)

- **The Terraform module is one instance per node** (`module.node["name"]`). Rendering the cluster without a node makes a plan that
  deletes that node's resources. A `tf.update` today refuses any delete or replace (`ALLOWED["update"]` in `plan.py`), so a removal
  needs its own rule; it cannot just relax the update rule.
- **A plan with no changes skips approval and adopts the parameters** (`_nothing_to_do`, `_adopt_params`). For a removal that would
  drop a node from the desired state while its machine still exists, so a removal must insist the plan deletes what it names.
- **Teardown already checks ownership** (`foreign_machines`), and `start_update` and the apply step both run it, so a removal
  of a machine ECM did not create is refused by what exists.
- **Discovery stores only a count of shards per node** (`EsNode.shard_count`), plus health and the settings. Which index's copy
  sits on which node is not stored, so the "last copy of a shard" check needs a live read. The existing `ESClient` already has the
  calls (`shards()`, `nodes_stats()`, `settings()`) and is GET-only, which is all a check needs.
- **Elasticsearch writes are made by Ansible from the worker**, with the ECM API key and `uri`, as the rolling restart and the join
  check do. The discovery clients stay read-only, so this slice does not change them.
- **The pre-flight rights check** already says a removal needs only `VM.Allocate` on the pool, so no new Proxmox right is needed.
- **`es_ca_host` is the first electable node** of the nodes that remain. A converge issues certificates only to nodes that lack
  one, signing with the CA ECM stores, so moving the CA host to another node needs no new certificates (*to confirm* on a live run,
  see below).
- **Ownership** (`created_machines`) counts every machine named in a create's or add-node's recorded state. It does not yet stop
  counting a machine a later removal destroyed.

## The sequence

The operation is a `tf.update` whose change is `remove_nodes`: `render, init, plan, approval, drain, apply, configure`. The new
phase is `drain`, and it comes after approval and before Terraform, because the node must be emptied while it is still running.

1. **Plan (changes nothing).** The request names the nodes. ECM runs the refusals below against a fresh read of the cluster, renders
   the desired state without those nodes, and has Terraform plan it. The plan must delete **exactly** the named nodes' resources
   (everything under `module.node["name"].`) and nothing else, create nothing, and replace nothing. A plan that deletes fewer
   than the request names, or more, is rejected, and a plan with no changes is rejected too (see above). The plan page shows a table of
   the nodes, their host, VM ID, roles, shards and data to move, and any warning.
2. **Approve.** By digest, as for every other operation.
3. **Drain** (a new playbook, `remove_nodes.yml`, run by the worker). It checks again from the worker, right before touching
   anything, that the cluster is green with every node present and that the refusals below still hold. Then for each node:
   `PUT /_nodes/<node id>/shutdown` with `type: remove`, which has Elasticsearch move the node's shards to the other nodes, and poll
   `GET /_nodes/<node id>/shutdown` until it reports `COMPLETE`. If it reports `STALLED` or the wait runs out, the playbook
   stops, **cancels the shutdown** so the node is a normal member again, and the message says why (for example, no node could take a shard).
   Nothing has been destroyed at that point.
4. **Apply.** Terraform destroys the machines. They are empty, and the cluster has already stopped counting on them.
5. **Configure** runs the converge, and `remove_nodes.yml` then checks from the worker that the cluster is green with the remaining
   nodes, and deletes each node's shutdown record. The converge rewrites the remaining nodes' seed lists without the removed
   nodes, and restarts nothing.

The cluster's desired state loses the nodes as soon as Terraform has applied, as for every update, so a failed converge keeps the
change and Retry re-runs the configure. A **Retry after a failed drain** plans again and drains again (the shutdown call is safe to repeat).
A **Retry after the apply failed part way** plans again, and Terraform destroys what is left. The addresses and VMIDs of the
removed nodes become free when the parameters are adopted. The node numbers are not reused (`node_counter` only goes up).
The inventory rows of the destroyed machines and the removed nodes are dropped as a teardown does it, rather than waiting for the next sync.

## What is refused, and why

All are checked at plan time against a live read, and again by the playbook before it drains. Each refusal names the node, index
or host in plain words.

**The three the plan requires:**

1. **Quorum loss.** After the removal the cluster must still be a valid cluster: at least 3 master-eligible nodes, one node that
   holds data, and not a single node (the mode cannot be changed on a live cluster). The master-eligible nodes removed together must be
   **fewer than half** of those the cluster has now (the Elasticsearch rule for taking master-eligible nodes out without the voting
   exclusions API; *to confirm*). **The master spread rule also applies in reverse:** after the removal no host may hold more than
   `(master-eligible nodes - 1) // 2` of them. On the three-host lab this means that with five masters, removing **one** is refused
   wherever it is (four masters allow one per host), and removing **two** is accepted if the three that remain are on three hosts.
   It is the mirror of the add-node rule, and it is deliberate.
2. **Not enough disk left.** The data on the removed data nodes must fit on the data nodes that remain. ECM compares what is used on
   the removed nodes with the room on the remaining data nodes **below the cluster's low watermark** (read from the cluster settings,
   85% if unset), and refuses with the figures. It is a sum, so it can pass when one node is the only place a shard fits;
   the drain's `STALLED` is the backstop.
3. **The last copy of a primary shard.** A shard whose only started copy is on a node being removed is listed, and the removal is
   refused. So is a cluster that has any shard not started (not green), because a copy that is missing elsewhere makes the
   remaining one the last. Also refused: an index with more copies of a shard than there would be data nodes left to hold them
   (it would stay yellow for good).

**Others, from what the code and the API make unsafe:**

- A data-holding role (`data`, `data_content`, `data_hot`, `data_warm`, `data_cold`, `data_frozen`) that would have no node left.
  The shards of that tier could not move, and the drain would stall. A **warning**, not a refusal, for the last node with `ml`,
  `ingest`, `transform` or `remote_cluster_client`, since the cluster keeps working without them.
- A machine ECM did not create (the existing ownership check), and a node that is not in the cluster's recorded state.
- A cluster not built, with nothing recorded, with another operation running, or not green at its last sync.

## What has to be built

- **Rules** in `lifecycle.py`: `RemoveNodes` (the node names), the refusals above, and the new desired state with the nodes taken out.
  Validation of the shrunken `DesiredState` comes first, so the existing cluster rules do part of the work.
- **A plan rule** in `plan.py`: an update may delete only a given set of addresses, and must delete all of them. The address match
  is on the module instance, never a name prefix that could match `name-1` and `name-10`.
- **The `drain` phase** on `tf.update` for this change, the request kind and inventory for `remove_nodes.yml`, and an `es_drain`
  role (secrets in the private extra-vars file, redacted as the others are). A new request kind is the only change to `inventory.py`.
- **Ownership:** `created_machines` stops counting a machine a succeeded `remove_nodes` update destroyed, by connection, VMID and name,
  so a stranger's VM that later takes the VMID is not marked ECM's. The new teardown of the destroyed machines' inventory rows is
  shared with the existing one.
- **The API** (`POST /api/clusters/{id}/remove-nodes`) and **the UI**: a "Remove nodes" panel on the cluster page (a table of the
  nodes with their roles, shard counts and disk used, a choice of nodes, the refusal text shown before the plan is made), and the
  plan page's table. Operation details say "Remove nodes" and, on failure after a drain, whether the shutdown was cancelled.
- **Tests:** each refusal, with the quorum and host-spread cases from the three-host lab; the plan rule (an extra delete, a missing
  delete, a replace, a name that is a prefix of another); the drain playbook against the same kind of fake Elasticsearch as the
  rolling restart, with the real response shapes, including `STALLED`, a timeout, and the cancel; the operation with fakes (phase
  order, desired state, released addresses, ownership); and the live run below.

## Decisions for the operator

**The operator's answers (2026-11-07): all five proposals accepted.** On (5), the elected master may be removed "as long as it's not the only
master": the plan refuses it when it is the cluster's only master-eligible node, which the quorum rule (at least 3 must remain)
already covers, and the message says so in those words.

1. **Only copy of a shard.** *Proposed:* refuse, with no override in this slice, as the acceptance criteria say. The cost is that a cluster
   with zero-replica indices cannot lose a node through ECM even though the shutdown API would copy the data first. The alternative is
   to allow it after a typed acknowledgement that the node holds the only copy.
2. **Several nodes at once.** *Proposed:* allowed, of any mix, under the quorum rule above. The alternative is one node per operation,
   which is simpler but cannot take the test cluster from five masters to three.
3. **Confirmation.** *Proposed:* the operation page's approval by digest, plus typing the cluster name when the request is made, as the
   teardown does (the nodes and their disks are destroyed, and the operation is not reversible). The alternative is approval alone.
4. **A drain that stalls or times out.** *Proposed:* ECM cancels the shutdown itself and says so. The alternative is to leave the drain
   in place for the operator to look at, which keeps new shards off the node.
5. **The elected master.** *Proposed:* allowed, with a warning that a new master will be elected. The alternative is refusing it
   until it is not the elected one, which the operator could arrange only by restarting nodes.

## To confirm

- The shape of `GET /_nodes/<id>/shutdown`: the statuses (`NOT_STARTED`, `IN_PROGRESS`, `STALLED`, `COMPLETE`) and the field that says
  why a shutdown is stalled. The playbook stops, and cancels, if a field is missing, as the join check does.
- That the ECM API key (carrying the `elastic` user's rights) may call the node shutdown API, and that `type: remove` is right for a
  node that will not return.
- That Elasticsearch re-forms the voting configuration by itself when masters leave, when fewer than half go at once. If it needs the
  voting exclusions API, the playbook must call it before the drain and clear it after.
- That Terraform's destroy stops a drained machine cleanly through Proxmox and leaves no orphaned volume (the spike once saw an
  orphaned cloud-init volume after a destroy, and the teardown's live run did not check for one).
- That removing the first electable node, which is the CA host, leaves the converge able to run (it takes the next electable node).
- That tearing down a create after one of its nodes was removed is not refused as foreign: `start_cleanup` checks the create's own
  VMIDs, which still include the removed node's.

## Live test plan (the test cluster has seven nodes: three created, two ML-type, two master-eligible)

In this order, each ending on a green cluster, after the checks the plan itself makes:

1. **A refusal first:** remove one master-eligible node. It must be refused by the host rule with a message naming the host.
2. **Remove an ML-type node.** No shards, so the drain should complete at once; this exercises the plan rule, the apply and the converge.
3. **Remove the two added masters together** (five masters down to three). This is the first time ECM changes the voting configuration
   by removal, and the case the voting-exclusions question matters for.
4. **A refusal at the end:** try to remove one of the three remaining masters. It must be refused (fewer than three would remain).

Then tear the test cluster down; that teardown, after nodes were added and removed, is also what the checks in *To confirm* want.

## Risks

- A drain moves data while the cluster serves traffic and may be slow on a busy or large cluster; the wait limits are guesses until measured.
- The disk check is a sum and the shard check reads the cluster at one moment; a shard that grows or an index created between plan and
  approval is caught only by the playbook's repeat of the checks and by `STALLED`.
- Terraform destroys the machines, so a mistake in the plan rule is a mistake in what is deleted. The rule is the same kind of
  guard as the teardown's, and the tests above are meant to prove it.
- Removing master-eligible nodes is the one case where Elasticsearch's own safety, not ECM's rules, decides whether the cluster stays up.

## As built, and where it differs from the proposal

- **The operation** is `render, init, plan, approval, drain, apply, configure` as proposed. `configure` runs the converge and then the
  playbook's `after` phase (green with the nodes that remain, then clearing the shutdown records of nodes that are gone).
- **The rules** are `plan_remove_nodes` in `provisioning/lifecycle.py`. The cheap rules run first (the typed cluster name, the nodes, the
  quorum, and the shrunken state as a valid cluster), then one live read of the cluster with GET calls only (`ESClient` gained
  `shards_sized()`, with `bytes=b`, and `master()`). A cluster ECM cannot reach is refused: a removal is never planned from the last sync alone.
- **One refusal is looser than proposed.** A data tier role that would have no node left refuses the removal only when the node holds
  shards; otherwise it is a warning. The first version refused it always, and the first test of it showed that a default-roles node
  carries `data_frozen`, which nothing in a normal cluster uses, so any removal of the added nodes would have been refused for nothing.
- **The quorum rule** is as designed: at least 3 master-eligible nodes remain, fewer than half are removed at once, and after the removal
  no host holds more than `(masters - 1) // 2` of them. The message names the host. The elected master is allowed with a warning, and
  "the only master" is the same refusal as too few remaining (the message says it is the only master-eligible node when that is so).
- **What the playbook checks again before it drains** is only: the cluster is green with every node present, no shard is not started,
  and no shard would lose its last copy. It does **not** repeat the quorum and disk rules (those are the plan's, from a read taken
  at plan time); the shutdown reporting `STALLED` is the backstop for a disk or tier problem that appeared since. A stall, a timeout or
  any failure cancels every shutdown it asked for (the nodes are ordinary members again) and the message says nothing was destroyed.
  **A transient `STALLED` fails the drain too**, safely and with a retry that drains again; whether a real cluster reports one while it
  is still working is *to confirm*.
- **A retry after the apply** works because the plan rule accepts a plan with no changes only when this operation's own earlier apply
  succeeded and left none of the named nodes in state, and because the drain skips a node that is already gone. Without that, the
  rule that refuses a plan with nothing to delete would have trapped a retry.
- **Ownership:** `foreign_machines` reads the removed nodes' VMIDs from the change (they are no longer in the parameters), so the check
  covers exactly the machines being destroyed; `removed_machines` stops `created_machines` counting a machine a removal's apply destroyed.
  The removed machines' rows leave the Proxmox inventory and the cluster's node list when the apply succeeds, without waiting for a sync.
- **The UI:** a "Remove nodes" panel on the cluster page (nodes with roles, host and a mark for those that count towards the quorum; the
  cluster name is typed in a confirmation), and on the operation page a table of the nodes with the data to move, a danger-coloured
  "Approve and remove", and a failure message that says whether anything was destroyed.
- **Not built:** moving the voting exclusions API into the playbook (not needed while fewer than half go), a check that a removed node
  was the elected master after the fact, and the live run below.
- **Unverified on a real cluster:** all of it. In particular the shapes of `GET /_nodes/<id>/shutdown` and `GET /_nodes/shutdown`, that the
  API key may call them, that Elasticsearch re-forms the voting configuration by itself when masters leave, how long a drain takes, that
  Terraform's destroy stops a drained machine cleanly and leaves no orphaned volume, and that clearing a departed node's shutdown record works.
