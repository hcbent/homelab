# Resizing CPU and RAM: proposed design (Phase 5, slice 2)

**Status: PROPOSED on 2026-11-06. Nothing described here is built.** It is written for the operator to review before
any code, because it restarts the nodes of a live cluster one at a time, which is the riskiest thing ECM would do so
far. Items marked *to confirm* are assumptions that have not been checked against this project's Proxmox, provider
or Elasticsearch.

## What is known

- **The VM module** sets `cpu { cores }` and `memory { dedicated }` from the desired state, with `started = true` and no
  hotplug settings (`provisioning/hcl.py`). So a change to either is a change to a VM that is running.
- **Proxmox applies CPU and memory changes when the VM is stopped and started again**, not live (*to confirm* for this
  Proxmox version and these VMs). The provider can reboot a VM after an update (*to confirm*: the setting's name and its
  default). Either way, **`terraform apply` can restart VMs by itself, and ECM currently applies two at a time** (`ECM_TF_PARALLELISM`
  defaults to 2). Left alone, a resize would restart two nodes at once and could lose the master quorum.
- **Whether Terraform changes CPU and RAM in place or replaces the VM** is *to confirm*. The `tf.update` rule already rejects any plan
  that replaces or deletes, so a replace is stopped at plan time, not applied.
- **The heap** comes from `es_heap_mb` (half of RAM, at most 31 GB, unless pinned) and is written by the `es_node` role,
  but a converge never restarts a node, so a new heap takes effect only when the node restarts.
- **Elasticsearch's own rolling restart procedure** (verified against
  `/docs/deploy-manage/maintenance/start-stop-services/full-cluster-restart-rolling-restart-procedures`, 2026-11-06): set
  `cluster.routing.allocation.enable` to `primaries`, optionally flush, stop **one** node, make the change, start it and
  confirm it joined, set the setting back to `null`, wait for the cluster to be stable, repeat for the next node. It also
  warns that a node above the disk low watermark restarts slowly. The node shutdown API (`type: restart`) is named in
  ARCHITECTURE section 7; its behaviour has **not** been checked here, so this design does not use it.
- **An approval covers one saved plan**, applied exactly. A resize has several applies, which is the main design problem.

## The sequence

Once, before anything changes (any failure here changes nothing):

1. The cluster is built, has recorded state, and no operation is running.
2. Every node has joined and health is green. A single-node cluster is refused (see Decisions).
3. No node to be restarted is above the disk low watermark.
4. Each Proxmox host has the CPU and memory the increase needs, from the last sync (a decrease needs nothing).
5. A pinned heap that would exceed half the new RAM is refused with the reason; otherwise the heap is recomputed.
6. ECM plans the whole change with Terraform and shows it: "change N virtual machines", and that each node restarts, in what
   order. **One approval covers the whole rolling change.**

Then, for each node in order, with the per-cluster lock held throughout:

1. **Gate:** health is green and every node is present. If not, stop here, before touching this node.
2. Set `cluster.routing.allocation.enable` to `primaries`.
3. Flush.
4. Converge **this node only** (Ansible `--limit`), so its new heap is written. Nothing restarts.
5. Apply Terraform for **this VM only**, one operation at a time (`-target`, parallelism 1). The VM restarts with the new size.
6. Wait for the node to rejoin and every primary to be active (yellow or better), with a time limit.
7. Set the allocation setting back to `null`, then wait for green, with a time limit.

**The approval rule for step 5:** each per-node plan is made fresh and must be exactly that node's slice of the approved plan: the
same address, only an in-place change, nothing else. Anything else (a replace, a delete, another resource) stops the
operation, and nothing past it is applied. This replaces "apply the exact saved plan" for this operation kind with
"apply only what the approved plan already showed", and it is the part most worth reviewing.

**Order:** coordinating-only nodes, then data nodes that are not master-eligible, then master-eligible nodes, the currently
elected master last (found with `_cat/master`). With three masters only one is ever down at a time because of the gate.

## When something goes wrong

- The operation stops at the first node that fails a gate, fails to apply, or does not come back in time. Nodes already done stay
  done. Nothing is rolled back (a rollback would be another restart).
- The cluster's desired state is updated node by node as each VM's change applies, so the record matches reality at every point.
- **Retry** plans again. A node already at the new size shows no change and is skipped (its converge still runs, which is
  harmless), so Retry resumes at the node that failed.
- If the operation stops while allocation is restricted, the error says so in plain words. See Decisions for what ECM does
  about it, because leaving it restricted quietly means new replicas never get allocated.

## What has to be built

- **An Elasticsearch client that can write** (cluster settings, flush) and wait on health. Discovery's clients are GET-only on
  purpose; this is a separate, small one, using the API key and CA ECM already stores.
- **Ansible `--limit`** on the request, so one node can be converged.
- **Terraform `-target`** for plan and apply in the runner, and the per-node check against the approved plan.
- **The operation:** a `resize` change for `tf.update` whose apply phase runs the sequence above, recording progress (which nodes
  are done) in the operation's result so a resumed run knows where it was, and logging each step.
- **The rules** in `lifecycle.py`: the pre-checks above, the order, the heap.
- **The UI:** a "Resize" panel on the cluster page (cores and RAM, for chosen nodes), and the plan page showing the order.
- **Tests with fakes** for every gate, refusal, failure and retry; **one live run on a disposable three-node cluster**, which
  is also where the *to confirm* items get answered. Nothing here can be proven offline.

## Decisions for the operator

1. **Who restarts the VM.** *Proposed:* Terraform, with a targeted apply per VM, so ECM gains no new way to power machines on or
   off. The alternative is ECM calling the Proxmox power API itself, which needs a new write path and a new token right.
2. **A single-node cluster.** *Proposed:* refused, because a restart means downtime and there is no replica. The alternative
   is to allow it when the request says it accepts the downtime.
3. **A stop while allocation is restricted.** *Proposed:* once every node is present again, ECM sets the allocation setting back
   itself and says so; if a node is still missing, it leaves the setting alone and says so loudly in the error. The
   alternative is to always leave it for the operator.
4. **Smaller sizes.** *Proposed:* allowed, with the same sequence (a decrease needs no capacity check), refusing RAM below 2 GiB
   and cores below 1. The alternative is to grow only.

## Risks

- **A node that does not come back** after its VM restarts leaves a cluster one node down and the operation stopped. The gate
  keeps it from taking a second node, but the cluster is degraded until someone looks.
- **The provider may replace a VM** for a CPU or memory change. The plan rules reject that, so it would show up as a refused plan
  rather than a lost node, but it would make this slice impossible as designed.
- **Time limits** (wait for rejoin, wait for green) are guesses until measured on this cluster.
- **Load:** the restarts happen while the cluster serves traffic; a busy cluster may take longer to go green between nodes.
