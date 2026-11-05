# Milestone 0: provider spike findings

Date: 2026-11-05. Provider: `bpg/proxmox` 0.119.0. Terraform 1.17.0. Target: one disposable VM (VMID 500) on pve2, cloned from template 8000 on pve1.

## Verdict

**Go for `bpg/proxmox`.** All five operations worked and repeated. The Telmate fallback was not needed.

| Check | Result | Notes |
|---|---|---|
| Clone template 8000 (pve1) to pve2 | passed | Works because the template disk is on shared storage (`tank`, NFS). Create took 1m26s with a 256 GB disk, 44s on a repeat. |
| Add a second 256 GB disk on `tank` | passed | Raw format, `scsi1`. |
| Static IP via cloud-init | passed | `192.168.10.211/24`, gateway `192.168.10.1`. Proxmox held the config and the VM answered a ping within about 15s of boot. The guest agent was off. |
| Resize the data disk | passed | 256 to 300 GB was an in-place update (2s), same volume path, no recreate, no drift afterwards. The filesystem inside the guest is not grown by this. |
| Import with a zero-diff plan | passed, with conditions | Not zero-diff with the creation config (see below). Zero-diff with an adoption-style config. |

## Adoption rules (import must be zero-diff)

Importing VM 500 into the creation config planned **1 to add, 1 to destroy**. Phase 7 rejects any plan with a delete or replace, so a creation config must never be reused for adoption. A separate adoption config reached zero diff when it:

1. **Has no `clone` block.** The clone source is not recoverable from a live VM, and the block forces replacement.
2. **Declares the settings the VM inherited from its template.** Here that was the serial console device, the `serial0` VGA setting and the cloud-init drive interface (`ide2`). Tags must be in sorted order.
3. **Ignores `operating_system`.** The provider does not read `operating_system.type` back on import, so declaring it always shows a change.
4. **Ignores `initialization[0].user_account`.** It holds a password and SSH keys, and adoption must never store secrets.

Adoption configs must therefore be generated from the live VM, not from templates.

## Implications for ECM

- **Token model.** Proxmox deletes permissions on `/vms/<id>` when that VM is destroyed. A token with rights on a single VMID loses them on destroy and gets a 403 on the next create. ECM needs a resource pool (or a path above the VMs) for its token. A pool named `ecm` is used for this.
- **Pool visibility.** The provider could not read pool membership back and showed `pool_id` as a pending in-place change. Either grant `Pool.Audit`, or ignore `pool_id` on adopted VMs.
- **Rights on the pool are powerful.** A token that can allocate and power-manage VMs on a pool can destroy anything placed in it. Keep real VMs out of the ECM pool unless that is intended.
- **Failed creates need cleanup.** A create that failed after the clone left a stopped VM that Terraform still tracked, plus an orphaned cloud-init volume on `tank`. ECM's retry path has to detect and remove partial resources, then re-plan. A saved plan goes stale after a failed apply.
- **Guest agent.** Leave it off in provisioning configs unless the template runs it. With it on, apply waits for the agent and hangs if it never answers.
- **Provider install can fail.** GitHub release downloads returned 504 for `terraform init`, on the build machine and on the user's own machine. The provider was fetched with `gh release download` instead, and its SHA-256 was checked against the Terraform Registry's published value and the release's `SHA256SUMS`. It was installed with `-plugin-dir`, which skips Terraform's signature check. ECM's runner image should vendor the provider.
- **Cross-host clone.** It worked only because the template disk is on shared storage. Placement logic must check that before choosing a different host from the template's.

## Not covered

- Cross-host clone when the template disk is on host-local storage.
- Growing the filesystem inside the guest after a disk resize (Ansible's job).
- Behaviour with the guest agent enabled.
- Why the first destroy left a cloud-init volume that blocked the next create. Later destroys left nothing, so it was not reproduced.

## Files

`main.tf`, `variables.tf` and `versions.tf` are the creation config. `adopt/` is the adoption config used for the import check. State, plans, logs, the plugin directory and `proxmox.env` are gitignored and must never be committed.
