# Credential Rotation Checklist

This document tracks all credentials that were exposed in git history and need to be rotated before making the repository public.

## Status Legend
- ⬜ Not Started
- 🔄 In Progress
- ✅ Completed

---

## 🔴 CRITICAL - Rotate Immediately

### 1. AWS Access Keys
**Status:** ⬜ Not Started

**Exposed Credentials:**
- Access Key ID: `***REMOVED***`
- Access Key ID: `***REMOVED***`
- Secret Keys: Multiple (see security audit)

**Impact:** Full access to S3 buckets and AWS resources

**How to Rotate:**
1. Go to AWS IAM Console: https://console.aws.amazon.com/iam/
2. Navigate to **Users** → Find your user
3. Go to **Security Credentials** tab
4. Under **Access keys**, click **Actions** → **Deactivate** for each exposed key
5. Create new access key pair
6. Update the following locations with new keys:
   - Local ansible inventory files (not committed)
   - Vault: `vault kv put secret/aws/s3 access_key_id=NEW_KEY secret_access_key=NEW_SECRET`
   - Any CI/CD pipelines
7. Test that new keys work
8. Delete old deactivated keys

**Files that referenced these (now sanitized):**
- `ansible/inventory/*.example`
- `k8s/lab-cluster/aws_secret.yaml.example`

---

### 2. Root Password "***REMOVED***"
**Status:** ⬜ Not Started

**Exposed Password:** `***REMOVED***`

**Impact:** Admin access to multiple critical systems

**Systems Using This Password:**
- Elasticsearch clusters (username: bret)
- TrueNAS/FreeNAS SSH access (root)
- Paperless admin account
- Cerebro web interface
- Proxmox VMs
- Grafana admin

**How to Rotate:**

#### Elasticsearch Clusters:
```bash
# On each Elasticsearch node:
curl -X POST "localhost:9200/_security/user/bret/_password" \
  -H 'Content-Type: application/json' \
  -d '{"password" : "NEW_SECURE_PASSWORD"}'

# Store in Vault:
vault kv put secret/elasticsearch/credentials username=bret password=NEW_PASSWORD
```

#### TrueNAS/FreeNAS:
1. Login to TrueNAS web interface (http://192.168.1.195 or 192.168.2.24)
2. Go to **Accounts** → **Users** → **root** → **Edit**
3. Set new password
4. Store in Vault: `vault kv put secret/truenas/credentials root_password=NEW_PASSWORD`
5. Update SSH keys if using key-based auth instead

#### Paperless:
```bash
# In Paperless container:
python manage.py changepassword admin

# Or via environment variable in kubernetes deployment
# Update PAPERLESS_ADMIN_PASSWORD in values file
```

#### Cerebro:
- Update `docker/elastic/cerebro/config/application.conf` (local copy only)
- Update `k8s/eck/cerebro.yaml` (local copy only)
- Restart Cerebro service

#### Grafana:
```bash
# Reset via CLI:
grafana-cli admin reset-admin-password NEW_PASSWORD

# Or update in Prometheus Helm values
```

---

### 3. TrueNAS/FreeNAS API Key
**Status:** ⬜ Not Started

**Exposed API Key:** `***REMOVED***`

**Impact:** Full storage infrastructure control

**How to Rotate:**
1. Login to TrueNAS web interface
2. Go to **API Keys** (gear icon → API Keys)
3. Delete the exposed API key
4. Click **Add** to create new API key
5. Store new key in Vault:
   ```bash
   vault kv put secret/truenas/api api_key=NEW_API_KEY
   ```
6. Update local configuration files:
   - `k8s/freenas-storageclass.yaml` (local copy)
   - `k8s/helm/values/freenas-nfs.yaml` (local copy)
   - `k8s/helm/values/freenas-iscsi.yaml` (local copy)
7. Apply updated Kubernetes configs:
   ```bash
   kubectl apply -f k8s/freenas-storageclass.yaml
   ```

---

### 4. HashiCorp Vault Root Token & Unseal Keys
**Status:** ⬜ Not Started

**Exposed Token:** `***REMOVED***`
**Exposed Unseal Keys:** Multiple (see security audit)

**Impact:** Complete compromise of secrets management system

**How to Rotate:** ⚠️ **This requires complete Vault re-initialization**

1. **Export all secrets first:**
   ```bash
   # List all secrets
   vault kv list secret/

   # Export each secret path to a secure location
   for path in $(vault kv list -format=json secret/ | jq -r '.[]'); do
     vault kv get -format=json "secret/$path" > "/secure/backup/$path.json"
   done
   ```

2. **Stop Vault service:**
   ```bash
   sudo systemctl stop vault
   ```

3. **Delete Vault data directory:**
   ```bash
   sudo rm -rf /opt/vault/data/*
   ```

4. **Start Vault and re-initialize:**
   ```bash
   sudo systemctl start vault
   vault operator init -key-shares=5 -key-threshold=3
   ```

   **Save the new unseal keys and root token securely!**

5. **Unseal Vault:**
   ```bash
   vault operator unseal <KEY1>
   vault operator unseal <KEY2>
   vault operator unseal <KEY3>
   ```

6. **Login with new root token:**
   ```bash
   vault login <NEW_ROOT_TOKEN>
   ```

7. **Restore all secrets:**
   ```bash
   for file in /secure/backup/*.json; do
     path=$(basename "$file" .json)
     vault kv put "secret/$path" @"$file"
   done
   ```

8. **Create new service tokens for applications**

---

### 5. K3S Cluster Token
**Status:** ⬜ Not Started

**Exposed Token:** `***REMOVED***`

**Impact:** Unauthorized nodes can join cluster

**How to Rotate:**
1. On K3S master node, edit `/var/lib/rancher/k3s/server/token`
2. Or regenerate by reinstalling K3S (disruptive)
3. Alternative: Use Kubernetes RBAC to limit damage
4. Remove compromised nodes if any joined
5. Update `k8s/add_node_to_cluster.sh` with new token (local copy only)

**Note:** K3S token rotation is complex. Consider these options:
- Regenerate token: Requires reinstalling K3S
- Mitigate: Use network policies and RBAC to limit impact
- Monitor: Check for unauthorized nodes

---

## 🟠 HIGH PRIORITY - Rotate Soon

### 6. Elastic Fleet Enrollment Tokens
**Status:** ⬜ Not Started

**Exposed Tokens:**
- `***REMOVED***`
- `***REMOVED***`

**Impact:** Unauthorized agents can enroll in Fleet

**How to Rotate:**
1. Login to Kibana/Fleet
2. Go to **Fleet** → **Settings** → **Enrollment tokens**
3. Revoke exposed tokens
4. Create new enrollment token
5. Update files:
   - `ansible/playbooks/add_agent.yml` (local copy)
   - `k8s/elastic-agent-deploy.sh` (local copy)
6. Re-enroll any agents using old token

---

## 🟡 MEDIUM PRIORITY - Rotate When Convenient

### 7. Plex Claim Tokens
**Status:** ⬜ Not Started

**Exposed Tokens:**
- `***REMOVED***`
- `***REMOVED***`

**Impact:** Someone could claim your Plex server

**How to Rotate:**
1. Get new claim token from https://plex.tv/claim
2. If server is already claimed, unclaim it first
3. Update local Kubernetes manifests with new token
4. Redeploy Plex with new claim token

**Note:** Claim tokens expire after 4 minutes, so old tokens may already be invalid. However, if someone already claimed your server, you need to reclaim it.

---

### 8. Pi-hole Admin Password
**Status:** ⬜ Not Started

**Exposed Password:** `***REMOVED***`

**Impact:** DNS configuration access

**How to Rotate:**
```bash
# SSH into Pi-hole server
pihole -a -p

# Enter new password when prompted

# Update ansible/playbooks/deploy_pihole.yml (local copy)
```

---

## 📋 Rotation Progress Tracking

| Credential | Status | Date Rotated | Rotated By | Notes |
|------------|--------|--------------|------------|-------|
| AWS Access Keys | ⬜ | | | |
| Root Password | ⬜ | | | |
| TrueNAS API Key | ⬜ | | | |
| Vault Token | ⬜ | | | |
| K3S Token | ⬜ | | | |
| Fleet Tokens | ⬜ | | | |
| Plex Tokens | ⬜ | | | |
| Pi-hole Password | ⬜ | | | |

---

## ✅ Post-Rotation Checklist

After rotating all credentials:

- [ ] All critical credentials rotated
- [ ] All high priority credentials rotated
- [ ] New credentials stored securely in Vault
- [ ] All services tested with new credentials
- [ ] Local configuration files updated
- [ ] Git history cleaned (run `scripts/clean-git-history.sh`)
- [ ] Force pushed cleaned history to GitHub
- [ ] Repository made public (if desired)
- [ ] All collaborators notified to re-clone
- [ ] This checklist archived for future reference

---

## 🔐 Best Practices Going Forward

1. **Never commit secrets to git**
   - Use `.example` files with placeholders
   - Store actual secrets in Vault
   - Use External Secrets Operator for Kubernetes

2. **Use git hooks to prevent secret commits**
   - Install `gitleaks` or `git-secrets`
   - Add pre-commit hooks

3. **Regular secret rotation**
   - Rotate credentials every 90 days
   - Use automated secret rotation where possible

4. **Monitor for leaked secrets**
   - Enable GitHub secret scanning
   - Use tools like GitGuardian
   - Monitor AWS CloudTrail for unauthorized access

---

**Last Updated:** $(date +%Y-%m-%d)
**Generated by:** Claude Code
