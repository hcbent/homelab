# To do

Small known problems and follow-ups that are not part of a phase. Add an item when one is found; remove it when it is fixed (the
fix goes in `DECISIONS.md` if it taught anything).

## Does Terraform follow a VM that was moved to another host?

**Left over from 2026-11-08, when a restart found VM 500 on `pve1` while ECM had recorded `pve2`.** The operator decided the record should always reflect reality, and **that is done for ECM's own record**: after every Proxmox sync, `placement` is
updated to where the inventory last saw each machine (`provisioning/reality.py`, with an audit event `cluster.host_followed`). What is not known is what **Terraform** does with a VM that has left the host in its state (`node_name`):

- With the bpg provider, a VM moved outside Terraform may be refreshed into place (its `node_name` in state updated), or may look missing on the old node and be planned for **creation** (a duplicate VM ID, which Proxmox would refuse), or be planned for
  **replacement** (an update operation rejects that). Not tried. Now that ECM renders the host the VM is on, a plan whose state still names the old host may also want to **migrate** it.
- **A harmless way to find out:** on a cluster with a VM that has moved (`test-5a-01`), plan any update (for example *Add nodes*, one coordinating node), read the Terraform part of the log, and **cancel** the plan. Existing VMs should show no change.
  If `test-5a-01` shows a change, a refresh-only step (`terraform apply -refresh-only`, which updates state to reality and changes no machine) before an update's plan would be the fix.

Done when that plan has been read and either shows no change for the moved VM or a refresh-only step is added and tested.
