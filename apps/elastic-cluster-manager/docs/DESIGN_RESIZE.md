# Resizing CPU and RAM: proposed design, revision 2 (Phase 5, slice 2)

**Status: PROPOSED. Only the probe (below) is built, tested with fakes and not yet run on infra; the restart machinery is not.** Revision 2 (2026-11-06) follows the operator's direction: **Terraform
applies the changes, then an Ansible playbook does the rolling restart**, masters last, the cluster back to green between
nodes, and shard allocation restricted while a node is down. It replaces revision 1, which had ECM applying Terraform one VM at
a time. Items marked *to confirm* are assumptions that nothing has checked on this project's Proxmox, provider or cluster.

## What is known

Verified on 2026-11-06 (sources named):

- **Proxmox applies a hardware change on a stop-and-start of the VM.** `qm reboot` is documented as "Reboot the VM by shutting it
  down, and starting it again. Applies pending changes" (`pve.proxmox.com/pve-docs/qm.1.html`). The same page does not say that
  a reboot started inside the guest applies pending changes, so this design does not rely on one.
- **The provider's `reboot_after_update`** (bpg/proxmox, docs on its `main` branch) defaults to `true`: "whether the provider may
  automatically reboot or power off the VM during update operations when required to apply changes." If `false`, "updates that
  require taking the VM offline fail instead of being applied automatically", while "changes that are applied successfully but
  still need a later manual reboot emit a warning instead." **The page does not say which kind a `cores` or `dedicated`
  change is, and says to test it.** That is the one thing this design cannot promise yet (see the probe below).
- **Elasticsearch's rolling restart** (`/docs/deploy-manage/maintenance/start-stop-services/full-cluster-restart-rolling-restart-procedures`):
  set `cluster.routing.allocation.enable` to `primaries`, optionally flush, restart **one** node, confirm it joined, set the setting to
  `null`, wait until stable, repeat. A node over the disk low watermark restarts slowly.
- **In this code:** the VM module sets `cpu { cores }` and `memory { dedicated }` with no hotplug (`provisioning/hcl.py`); the `es_node`
  role writes the heap from `es_heap_mb`, but a converge never restarts a node (`es_allow_restart` is false), so a new heap
  takes effect only at the restart; the ECM API key is made with no role restriction, so it carries the `elastic` user's
  privileges (`es_bootstrap`); the worker already holds the Proxmox Terraform token and the cluster's CA.

*To confirm:* that the Terraform token has the right to restart VMs (`VM.PowerMgmt`; it must already be able to start them); that
`POST /nodes/{node}/qemu/{vmid}/status/reboot` is the API call behind `qm reboot`; and that Proxmox reports a pending change as
the running VM's config in a way that leaves the next `terraform plan` clean.

## The probe, which comes first

Before any restart machinery, build only the part that plans and applies the size change with `reboot_after_update = false`
and **no restart phase**, and run it on a disposable cluster. Either result is useful and neither restarts anything:

- **Terraform applies it and warns** that a reboot is still needed: the pending change sits on the VM, the approach in this
  document works, and the next step is the playbook.
- **Terraform fails** because the change needs the VM offline: the approach needs a different first step (see Fallback). The
  operation fails with the provider's own message, keeps its state, and changes no VM that was already updated.

## The sequence

The operation is a `tf.update` with an added last phase: `render, init, plan, approval, apply, configure, restart`.

1. **Plan (once, changes nothing).** The pre-checks below, then one Terraform plan of the whole change, shown as "change N
   virtual machines" with the restart order. **One approval covers the whole change, and apply is the one saved plan, exactly,
   as for every other operation**: this design needs no per-node plans or exceptions to that rule.
2. **Apply.** Terraform applies the approved plan with `reboot_after_update = false`, so it does not restart the VMs
   (*to confirm*, see the probe).
3. **Configure.** The existing converge writes each node's new heap setting. It restarts nothing.
4. **Restart.** A new playbook, `rolling_restart.yml`, run by the worker, does the rest.

**The playbook,** for each node in turn (`serial: 1` in effect), working from a node that is not the one being restarted:

1. **Skip it if it already runs at the target size** (the guest's vCPU count and memory against the desired state). This is
   what makes Retry resume where it stopped, with no record of its own to keep.
2. **Gate: health is green and every node has joined.** If not, stop before touching this node.
3. Set `cluster.routing.allocation.enable` to `primaries`. This is the setting Elasticsearch's procedure uses. `none` would
   also stop the restarting node's own shards from being allocated when it returns, which would leave the cluster red, so the
   design restricts replicas only (*my understanding of `none`; not checked here*).
4. Flush.
5. **Restart the VM through the Proxmox API** (the worker, using the Terraform token), which shuts the guest down cleanly,
   including Elasticsearch, and starts it again with the new size.
6. Wait for the machine to answer SSH, then for the node to rejoin and every primary to be active (yellow or better).
7. Set the allocation setting back to `null` and wait for green. Only then move to the next node.

**Order:** coordinating-only nodes, then data nodes that are not master-eligible, then master-eligible nodes, with the
currently elected master last (read from `_cat/master` while the playbook runs). The gate means only one node is down at a time.

## Pre-checks (all before anything changes)

The cluster is built, has recorded state and has no operation running; every node has joined and health is green; a
single-node cluster is refused (see Decisions); no node is over the disk low watermark; each Proxmox host has the CPU and memory an
increase needs, from the last sync; a pinned heap that would exceed half the new RAM is refused with the reason, and otherwise
the heap is recomputed (half of RAM, at most 31 GB); RAM below 2 GiB or cores below 1 is refused.

## When something goes wrong

- The playbook stops at the first node that fails a gate, does not come back in time, or fails to restart. Nodes already done
  stay done; nothing is rolled back.
- **Allocation:** if the playbook stops after restricting allocation and **every node is present again**, it sets the setting back to
  `null` itself and the error says so. If a node is still missing it leaves the setting alone and the error says, in plain
  words, that allocation is restricted to primaries and how to restore it, because leaving it restricted quietly means new
  replicas are never allocated.
- **Retry** plans again (no changes: Terraform already matches), skips the apply, runs the converge, and the playbook skips every
  node already at the target size.

## What has to be built

- The **probe** first: the HCL setting, the resize rules in `lifecycle.py`, the endpoint and the plan page, with no restart phase.
- **Inventory** variables for each host's Proxmox node and VMID, and its restart group.
- **A request kind and playbook** for the restart: secrets (the ES API key, the Proxmox token) passed in the private extra-vars
  file and redacted from the log like the others, plus the CA, and an `es_rolling_restart` role.
- **The `restart` phase** on `tf.update` for a resize, and the UI panel and the order on the plan page.
- **Tests.** The playbook can be tested offline with real Ansible against small local fake HTTP servers for the Elasticsearch and
  Proxmox calls and a stand-in for ssh, as the first-boot wait is: they would record the order of calls and prove that masters
  are last, that allocation is restricted before each restart and restored after it, that green is awaited between nodes, and
  that a failure stops the run. **One live run on a disposable three-node cluster** answers the *to confirm* items.

## Decisions

Settled by the operator: Terraform applies; an Ansible playbook restarts, one node at a time; masters last; green between
nodes; shard allocation restricted while a node is down.

*Proposed, still open:*

1. **Single-node cluster.** Refuse (a restart means downtime and there is no replica), or allow it when the request accepts the downtime.
2. **A stop while allocation is restricted.** Restore it automatically once every node is present (proposed), or never.
3. **Smaller sizes.** Allowed with the same sequence (proposed), or grow only.

## Fallback if the probe fails

If Terraform will not apply a CPU or memory change to a running VM with the restart turned off, the first step becomes the
playbook's: shut the VM down through the Proxmox API, let Terraform apply the change to the stopped VM, then start it. That needs
Terraform to run once per node with a gate between, which brings back a per-node plan checked against the approved one. The other
route, enabling CPU and memory hotplug, needs NUMA and guest support and is not assumed.

## Risks

- A node that does not come back leaves the cluster one node down and the operation stopped; the gate stops a second node going down.
- Time limits (SSH back, node rejoined, green) are guesses until measured on this cluster.
- The restarts happen while the cluster serves traffic; a busy cluster may take longer to reach green between nodes.
- The playbook holds the Terraform token and the ES API key for the run, so both must be kept out of every log line.
