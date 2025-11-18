# Task Group 1: Completion Checklist

Print this checklist or keep it handy while completing Task Group 1.

## Prerequisites

- [ ] Vault is accessible at https://192.168.10.101:8200
- [ ] Vault CLI is installed and configured
- [ ] You have admin access to Tailscale account
- [ ] You have access to Tailscale admin console

## Step 1: Organization Setup

- [ ] Open Tailscale admin console: https://login.tailscale.com/admin
- [ ] Navigate to Settings > General
- [ ] Note organization name: ______________________________
- [ ] Note tailnet name: __________________________________
- [ ] Create organization-info.txt from template:
  ```bash
  cd /Users/bret/git/homelab/tailscale
  cp organization-info-template.txt organization-info.txt
  ```
- [ ] Edit organization-info.txt with your details
- [ ] Save the file

## Step 2: Create Tags in ACL (if needed)

- [ ] Open ACL editor: https://login.tailscale.com/admin/acls
- [ ] Check if `tag:kubernetes` and `tag:homelab` exist
- [ ] If not, add to `tagOwners` section:
  ```json
  "tagOwners": {
    "tag:kubernetes": ["autogroup:admin"],
    "tag:homelab": ["autogroup:admin"]
  }
  ```
- [ ] Save the ACL temporarily (will replace in Step 5)

## Step 3: Generate Auth Key

- [ ] In Tailscale admin console, go to: Settings > Keys
- [ ] Click "Generate auth key..."
- [ ] Configure settings:
  - [ ] Description: `homelab-kubernetes-cluster`
  - [ ] Reusable: **CHECKED**
  - [ ] Ephemeral: **UNCHECKED**
  - [ ] Tags: `tag:kubernetes` **AND** `tag:homelab` (both!)
  - [ ] Expiration: **365 days** (or maximum allowed)
- [ ] Click "Generate key"
- [ ] Copy the auth key immediately (starts with `tskey-auth-`)
- [ ] Store temporarily in a secure location

Auth key: tskey-auth-_______________________________________

## Step 4: Store Auth Key in Vault

- [ ] Open terminal
- [ ] Set Vault environment:
  ```bash
  export VAULT_ADDR="https://192.168.10.101:8200"
  export VAULT_SKIP_VERIFY="true"
  ```
- [ ] Login to Vault:
  ```bash
  vault login
  ```
- [ ] Enter your Vault token when prompted
- [ ] Run the storage script:
  ```bash
  cd /Users/bret/git/homelab/tailscale
  ./scripts/store-auth-key.sh
  ```
- [ ] Paste the auth key when prompted
- [ ] Verify you see success messages
- [ ] Verify storage:
  ```bash
  vault kv get secret/tailscale/auth-keys
  ```
- [ ] Confirm auth key is displayed (masked)

## Step 5: Apply ACL Policy

- [ ] Open ACL editor: https://login.tailscale.com/admin/acls
- [ ] Open the policy file:
  ```bash
  cat /Users/bret/git/homelab/tailscale/acl-policy-permissive.json
  ```
- [ ] Copy the entire contents (Cmd+A, Cmd+C)
- [ ] Paste into the ACL editor (replace existing content)
- [ ] Click "Save" or "Apply"
- [ ] Verify no validation errors appear
- [ ] Confirm policy is marked as "Active"

## Step 6: Verification

### Verify Organization
- [ ] Organization name documented in organization-info.txt
- [ ] Tailnet name documented in organization-info.txt

### Verify Auth Key
- [ ] Auth key stored in Vault
- [ ] Vault path is: secret/tailscale/auth-keys
- [ ] Can retrieve with: `vault kv get secret/tailscale/auth-keys`

### Verify Vault Policy
- [ ] Vault policy `tailscale-k8s` exists
- [ ] Check with: `vault policy read tailscale-k8s`
- [ ] Policy allows read access to auth key path

### Verify ACL Policy
- [ ] ACL policy applied in Tailscale console
- [ ] Tags `tag:kubernetes` and `tag:homelab` defined in tagOwners
- [ ] Policy allows access to all services (permissive)
- [ ] No validation errors

## Step 7: Git Operations

- [ ] Review files to commit:
  ```bash
  cd /Users/bret/git/homelab
  git status
  ```
- [ ] Files to commit (safe - no secrets):
  - [ ] tailscale/README.md
  - [ ] tailscale/QUICKSTART.md
  - [ ] tailscale/CHECKLIST.md
  - [ ] tailscale/acl-policy-permissive.json
  - [ ] tailscale/organization-info-template.txt
  - [ ] tailscale/.gitignore
  - [ ] tailscale/scripts/store-auth-key.sh
  - [ ] agent-os/specs/2025-11-18_tailscale-migration/implementation/*
  - [ ] agent-os/specs/2025-11-18_tailscale-migration/tasks.md (updated)
  - [ ] agent-os/specs/2025-11-18_tailscale-migration/planning/visuals/*

- [ ] Files to NOT commit (sensitive):
  - [ ] tailscale/organization-info.txt (if it contains sensitive details)

- [ ] Stage and commit:
  ```bash
  git add tailscale/
  git add agent-os/specs/2025-11-18_tailscale-migration/
  git commit -m "Add Task Group 1: Tailscale account setup

  - Add Vault auth key storage script
  - Add permissive ACL policy for initial deployment
  - Add comprehensive documentation and quick start guide
  - Add implementation instructions and summary
  - Add architecture diagrams and checklists

  Task Group 1 ready for user execution.

  Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>"
  ```

## Step 8: Update Tasks

- [ ] Open tasks.md:
  ```bash
  vim /Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/tasks.md
  ```
- [ ] Mark Task Group 1 subtasks as complete:
  - [ ] Change `- [ ] 1.1` to `- [x] 1.1`
  - [ ] Change `- [ ] 1.2` to `- [x] 1.2`
  - [ ] Change `- [ ] 1.3` to `- [x] 1.3`
  - [ ] Change `- [ ] 1.4` to `- [x] 1.4`
- [ ] Save the file
- [ ] Commit the update:
  ```bash
  git add agent-os/specs/2025-11-18_tailscale-migration/tasks.md
  git commit -m "Mark Task Group 1 as complete"
  ```

## Completion Criteria

Task Group 1 is complete when ALL of the following are true:

- [x] Implementation files created (done by agent)
- [ ] Organization details documented
- [ ] Auth key generated with correct settings
- [ ] Auth key stored in Vault at secret/tailscale/auth-keys
- [ ] Vault policy tailscale-k8s created
- [ ] ACL policy applied in Tailscale admin console
- [ ] All configuration files committed to git
- [ ] Tasks.md updated with completed checkboxes

## Next Steps

After completing this checklist:

1. [ ] Review the summary:
   ```bash
   cat /Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-1-summary.md
   ```

2. [ ] Proceed to Task Group 2: Tailscale Kubernetes Operator Deployment

3. [ ] Keep this checklist for reference

## Troubleshooting

If you encounter issues:

1. Check the troubleshooting sections in:
   - `/Users/bret/git/homelab/tailscale/QUICKSTART.md`
   - `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-1-instructions.md`

2. Verify prerequisites:
   - Vault accessible
   - Tailscale admin access
   - Correct permissions

3. Review error messages carefully

4. Check Vault logs if storage fails

5. Validate JSON syntax if ACL fails

## Time Estimate

- Reading instructions: 10 minutes
- Completing steps: 15-30 minutes
- Verification: 5 minutes
- Git operations: 5 minutes

**Total: 35-50 minutes**

## Notes

- Keep auth key secure - never commit to git
- The ACL policy is permissive initially (will be tightened later)
- All sensitive data is stored in Vault, not in git
- This foundation is required for all subsequent task groups

## Contact

For questions or issues:
- Review documentation in `/Users/bret/git/homelab/tailscale/`
- Check Tailscale docs: https://tailscale.com/kb
- Check Vault docs: https://developer.hashicorp.com/vault/docs

---

**Date Started:** _____________________

**Date Completed:** _____________________

**Completed By:** _____________________

**Notes:**
