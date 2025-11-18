# Task Group 1: Tailscale Account Setup - Implementation Instructions

## Overview

This document provides step-by-step instructions for completing Task Group 1: Tailscale Account Setup. This includes configuring your Tailscale account, generating auth keys, storing them in Vault, and setting up a permissive initial ACL policy.

## Prerequisites

- Tailscale account already created
- Vault instance running at https://192.168.10.101:8200
- Vault CLI access configured
- Access to Tailscale admin console

## Task 1.1: Create/Verify Tailscale Account Organization

### Steps:

1. **Access Tailscale Admin Console**
   - Navigate to: https://login.tailscale.com/admin
   - Log in with your Tailscale account credentials

2. **Verify Organization Settings**
   - Go to Settings > General
   - Note your organization name
   - Note your tailnet name (typically ends with `.ts.net`)

3. **Document Organization Details**
   - Create a file to store this information:
   ```bash
   cat > /Users/bret/git/homelab/tailscale/organization-info.txt <<EOF
   Organization Name: [YOUR_ORG_NAME]
   Tailnet Name: [YOUR_TAILNET_NAME]
   Admin Console: https://login.tailscale.com/admin
   Date Configured: $(date)
   EOF
   ```

## Task 1.2: Generate Reusable, Tagged Auth Keys

### Steps:

1. **Navigate to Auth Keys Section**
   - In Tailscale Admin Console, go to Settings > Keys
   - Click "Generate auth key..."

2. **Configure Auth Key Settings**
   - Description: `homelab-kubernetes-cluster`
   - Check "Reusable" (allows using the same key for multiple nodes)
   - Check "Ephemeral" is UNCHECKED (we want persistent devices)
   - Tags: Add tags `tag:kubernetes` and `tag:homelab`
     - Note: You may need to create these tags first in Settings > ACLs
   - Expiration: Set to 365 days (1 year) or maximum allowed
   - Click "Generate key"

3. **Copy Auth Key**
   - Copy the generated auth key immediately (it won't be shown again)
   - Store it temporarily in a secure location
   - The key will look like: `tskey-auth-xxxxx-yyyyy`

### Alternative: Create Tags in ACL First

If tags don't exist yet, you'll need to add them to your ACL policy first:

1. Go to Access Controls in Tailscale Admin Console
2. Add to the `tagOwners` section:
   ```json
   "tagOwners": {
     "tag:kubernetes": ["autogroup:admin"],
     "tag:homelab": ["autogroup:admin"]
   }
   ```
3. Save the ACL policy
4. Then return to generate the auth key with these tags

## Task 1.3: Store Auth Keys in Vault

### Steps:

1. **Login to Vault**
   ```bash
   export VAULT_ADDR="https://192.168.10.101:8200"
   export VAULT_SKIP_VERIFY="true"
   vault login
   # Enter your Vault token when prompted
   ```

2. **Run the Vault Storage Script**
   ```bash
   /Users/bret/git/homelab/tailscale/scripts/store-auth-key.sh
   ```

   This script will:
   - Prompt for your Tailscale auth key
   - Store it in Vault at `secret/tailscale/auth-keys`
   - Verify the storage was successful
   - Test retrieval from Vault

3. **Verify Storage**
   ```bash
   vault kv get secret/tailscale/auth-keys
   ```

   Expected output:
   ```
   ====== Secret Path ======
   secret/data/tailscale/auth-keys

   ======= Metadata =======
   Key                Value
   ---                -----
   created_time       [timestamp]
   custom_metadata    <nil>
   deletion_time      n/a
   destroyed          false
   version            1

   ==== Data ====
   Key         Value
   ---         -----
   auth_key    tskey-auth-xxxxx-yyyyy
   ```

## Task 1.4: Configure Tailscale ACL Policy (Permissive Initial State)

### Steps:

1. **Review the Permissive ACL Policy**
   - The policy file has been created at:
     `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
   - This policy allows all users to access all services
   - It includes the necessary tag definitions for Kubernetes nodes

2. **Apply ACL Policy in Tailscale Admin Console**
   - Navigate to: https://login.tailscale.com/admin/acls
   - Click "Edit ACL"
   - Copy the contents of `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
   - Paste into the ACL editor
   - Click "Save"

3. **Verify ACL Policy**
   - The policy should pass validation
   - All syntax errors should be resolved
   - The policy should be marked as "Active"

### ACL Policy Features:

The permissive policy includes:
- Tag ownership definitions for `tag:kubernetes` and `tag:homelab`
- Host definitions for service groups (media apps, home apps, etc.)
- Wide-open access rules allowing all users to access all services
- SSH access rules
- Test infrastructure for validation

### Future ACL Tightening:

After the 2-week validation period, we will:
- Restrict access by user groups
- Implement per-service access controls
- Add more granular SSH policies
- Enable posture checks if needed

## Verification Checklist

After completing all tasks, verify:

- [ ] Tailscale organization name documented
- [ ] Tailnet name documented
- [ ] Auth key generated with correct settings:
  - [ ] Reusable: Yes
  - [ ] Ephemeral: No
  - [ ] Tags: kubernetes, homelab
  - [ ] Expiration: 1 year or maximum
- [ ] Auth key stored in Vault at `secret/tailscale/auth-keys`
- [ ] Vault storage verified with successful retrieval
- [ ] Vault policy allows Kubernetes to read auth keys
- [ ] ACL policy applied in Tailscale Admin Console
- [ ] ACL policy includes tag definitions
- [ ] ACL policy is permissive (all users can access all services)
- [ ] ACL policy saved to git repository

## Files Created

The following files have been created in your repository:

1. `/Users/bret/git/homelab/tailscale/scripts/store-auth-key.sh`
   - Script to store auth key in Vault
   - Includes verification and testing

2. `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
   - Permissive ACL policy for initial deployment
   - Version-controlled for infrastructure-as-code

3. `/Users/bret/git/homelab/tailscale/organization-info.txt`
   - Organization and tailnet details
   - To be populated by you

4. `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-1-instructions.md`
   - This instruction document

## Next Steps

After completing Task Group 1:

1. Mark all subtasks as complete in `tasks.md`
2. Proceed to Task Group 2: Tailscale Kubernetes Operator Deployment
3. Keep auth key documentation secure and accessible

## Troubleshooting

### Issue: Cannot access Tailscale Admin Console

**Solution:** Verify you're logged into the correct Tailscale account. If you have multiple accounts, ensure you're using the one for your homelab.

### Issue: Auth key generation fails

**Solution:**
- Ensure you have admin permissions on the tailnet
- Verify tags exist in ACL policy before trying to use them
- Check that you're not exceeding the auth key limit

### Issue: Vault storage fails

**Solution:**
- Verify Vault is accessible: `curl -k https://192.168.10.101:8200/v1/sys/health`
- Ensure you're authenticated: `vault token lookup`
- Check KV v2 secrets engine is enabled: `vault secrets list`
- Verify path: `secret/` should be listed

### Issue: ACL policy validation fails

**Solution:**
- Check JSON syntax is valid
- Ensure all referenced tags are defined in `tagOwners`
- Verify host definitions don't conflict
- Check for missing commas or brackets

## Security Notes

- The auth key is stored in Vault and should never be committed to git
- The ACL policy file is safe to commit to git (it contains no secrets)
- Keep the organization info file private (add to .gitignore if it contains sensitive details)
- Auth keys should be rotated annually or if compromised
- The permissive ACL is temporary and will be tightened after validation

## Support

For issues or questions:
- Tailscale Documentation: https://tailscale.com/kb
- Vault Documentation: https://developer.hashicorp.com/vault/docs
- Homelab repository: https://github.com/yourusername/homelab
