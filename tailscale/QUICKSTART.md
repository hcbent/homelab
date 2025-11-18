# Tailscale Quick Start Guide

## Task Group 1: Account Setup (This Task)

### Step 1: Access Tailscale Admin Console

```bash
# Open in browser
https://login.tailscale.com/admin
```

### Step 2: Document Organization Info

```bash
cd /Users/bret/git/homelab/tailscale
cp organization-info-template.txt organization-info.txt
# Edit organization-info.txt with your details from the admin console
```

### Step 3: Generate Auth Key

1. In Tailscale Admin Console, go to: **Settings > Keys**
2. Click **"Generate auth key..."**
3. Configure:
   - Description: `homelab-kubernetes-cluster`
   - Reusable: **Checked**
   - Ephemeral: **Unchecked**
   - Tags: `tag:kubernetes`, `tag:homelab` (create in ACL if needed)
   - Expiration: **365 days**
4. Copy the generated auth key

### Step 4: Store Auth Key in Vault

```bash
cd /Users/bret/git/homelab/tailscale
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY="true"

# Login to Vault
vault login

# Run the storage script
./scripts/store-auth-key.sh
# Paste your auth key when prompted

# Verify storage
vault kv get secret/tailscale/auth-keys
```

### Step 5: Apply ACL Policy

1. Open ACL editor: https://login.tailscale.com/admin/acls
2. Copy contents of `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
3. Paste into the ACL editor
4. Click **"Save"**
5. Verify no validation errors

## Verification Checklist

- [ ] Tailscale admin console accessed
- [ ] Organization name and tailnet name documented
- [ ] Auth key generated with correct settings (reusable, tags, 1 year)
- [ ] Auth key stored in Vault at `secret/tailscale/auth-keys`
- [ ] Vault policy `tailscale-k8s` created
- [ ] ACL policy applied in Tailscale admin console
- [ ] ACL policy saved to git (`acl-policy-permissive.json`)

## Quick Commands

### Vault Operations

```bash
# Set Vault environment
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY="true"

# Login
vault login

# Retrieve auth key
vault kv get -field=auth_key secret/tailscale/auth-keys

# View policy
vault policy read tailscale-k8s

# Check Vault health
curl -k https://192.168.10.101:8200/v1/sys/health
```

### Tailscale URLs

- **Admin Console:** https://login.tailscale.com/admin
- **ACL Editor:** https://login.tailscale.com/admin/acls
- **Auth Keys:** https://login.tailscale.com/admin/settings/keys
- **DNS Settings:** https://login.tailscale.com/admin/dns

## Common Issues

### Issue: Cannot create tags in auth key generation

**Solution:** Tags must be defined in ACL policy first.

1. Go to ACL editor
2. Add to `tagOwners`:
   ```json
   "tagOwners": {
     "tag:kubernetes": ["autogroup:admin"],
     "tag:homelab": ["autogroup:admin"]
   }
   ```
3. Save ACL policy
4. Return to auth key generation

### Issue: Vault login fails

**Solution:** Check Vault accessibility and token.

```bash
# Check connectivity
curl -k https://192.168.10.101:8200/v1/sys/health

# Verify you have a valid token
vault token lookup
```

### Issue: Script fails with "KV secrets engine not enabled"

**Solution:** Enable KV v2 secrets engine.

```bash
vault secrets enable -path=secret kv-v2
```

## Next Steps

After completing Task Group 1:

1. Update `tasks.md` to mark Task Group 1 as complete
2. Proceed to **Task Group 2: Tailscale Kubernetes Operator Deployment**
3. The auth key in Vault will be used by the Kubernetes operator

## Files Created

- `/Users/bret/git/homelab/tailscale/README.md`
- `/Users/bret/git/homelab/tailscale/QUICKSTART.md` (this file)
- `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
- `/Users/bret/git/homelab/tailscale/scripts/store-auth-key.sh`
- `/Users/bret/git/homelab/tailscale/organization-info-template.txt`
- `/Users/bret/git/homelab/tailscale/.gitignore`

## Support

- **Tailscale Docs:** https://tailscale.com/kb
- **Vault Docs:** https://developer.hashicorp.com/vault/docs
- **Spec:** `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/`
