# To do

Small known problems and follow-ups that are not part of a phase. Add an item when one is found; remove it when it is fixed (the
fix goes in `DECISIONS.md` if it taught anything).

## Forgetting or removing a node that is not master-eligible runs a converge that has nothing to change because of it

**Found 2026-11-08, from the same forget.** `discovery.seed_hosts` is built from the master-eligible nodes only, so taking a data, ingest, ML or coordinating-only node out of the record changes nothing the remaining nodes' configuration
refers to. The converge after a forget (and after a removal) still runs on every remaining node, rewriting any file that has drifted from the render (in the operator's forget it changed files on four of five nodes, probably the
first-converge drift described in `docs/DESIGN_RECOVERY.md`), and nothing restarts. It is safe, but it touches nodes the change did not concern.

Propose: run it only when a master-eligible node leaves (its address leaves the seed list), and otherwise skip the step and say so ("no remaining node's configuration refers to the removed nodes"). A removal would still run its check
that the cluster is green without them. The alternative is to keep running it, as a deliberate reconcile. Done when a forget or removal of non-master nodes skips the converge and says why, one of a master still runs it, and tests show both.

## Restart only the nodes whose configuration is waiting for a restart

**Left over from slice 5b (2026-11-08).** Every converge after an add, a removal or a forget says, per node, "has not been restarted; the change takes effect at the next rolling restart", but ECM does not record which nodes that
is, so the Restart nodes panel can only offer "Select every node", which restarts nodes that did not need it. Two ways to know: (1) have the playbook report the hosts where `Write elasticsearch.yml` (or the heap file) changed while
`es_allow_restart` was false, and keep that list on the cluster until those nodes restart; or (2) read it from each node when the restart is planned, by asking whether the configuration file is newer than the service's start time (an SSH
probe, since nothing else can tell). (2) needs no new state and cannot go stale; (1) needs a column and a migration. Done when the panel marks the nodes that are waiting and offers "Restart the nodes that are waiting".

## Does Terraform follow a VM that was moved to another host?

**Left over from 2026-11-08, when a restart found VM 500 on `pve1` while ECM had recorded `pve2`.** The operator decided the record should always reflect reality, and **that is done for ECM's own record**: after every Proxmox sync, `placement` is
updated to where the inventory last saw each machine (`provisioning/reality.py`, with an audit event `cluster.host_followed`). What is not known is what **Terraform** does with a VM that has left the host in its state (`node_name`):

- With the bpg provider, a VM moved outside Terraform may be refreshed into place (its `node_name` in state updated), or may look missing on the old node and be planned for **creation** (a duplicate VM ID, which Proxmox would refuse), or be planned for
  **replacement** (an update operation rejects that). Not tried. Now that ECM renders the host the VM is on, a plan whose state still names the old host may also want to **migrate** it.
- **A harmless way to find out:** on a cluster with a VM that has moved (`test-5a-01`), plan any update (for example *Add nodes*, one coordinating node), read the Terraform part of the log, and **cancel** the plan. Existing VMs should show no change.
  If `test-5a-01` shows a change, a refresh-only step (`terraform apply -refresh-only`, which updates state to reality and changes no machine) before an update's plan would be the fix.

Done when that plan has been read and either shows no change for the moved VM or a refresh-only step is added and tested.
