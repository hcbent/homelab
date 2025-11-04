# Secret Migration to Vault - Summary Report

**Date:** 2025-11-04
**Task Group:** 2 - Secret Organization and Migration to Vault
**Status:** Partially Complete

## Completed Tasks

### 2.2 Proxmox Credentials Migration ✅
**Vault Path:** `secret/homelab/proxmox/terraform`

Migrated credentials:
- `username`: root@pam
- `password`: [REDACTED]
- `ciuser`: bret
- `cipassword`: [REDACTED]

**Verification:**
```bash
vault kv get secret/homelab/proxmox/terraform
```

**Terraform Integration:**
- Updated `/Users/bret/git/homelab/tf/lab/versions.tf` to include Vault provider
- Updated `/Users/bret/git/homelab/tf/lab/provider.tf` to use Vault data sources
- Updated `/Users/bret/git/homelab/tf/lab/main.tf` to use Vault secrets for cloud-init
- Created `/Users/bret/git/homelab/tf/lab/terraform.tfvars.example` with Vault references

### 2.3 TrueNAS Credentials Migration ✅
**Vault Paths:**
- `secret/homelab/freenas/credentials` - API credentials
- `secret/homelab/freenas/ssh` - SSH credentials

Migrated credentials:
- API credentials: username, password, host, api_key
- SSH credentials: host, port, username, private_key

**Verification:**
```bash
vault kv get secret/homelab/freenas/credentials
vault kv get secret/homelab/freenas/ssh
```

**Configuration Files:**
- Created `/Users/bret/git/homelab/k8s/helm/values/freenas-iscsi.yaml.example` with Vault references

### 2.4 Elasticsearch Credentials Migration ✅
**Vault Paths:**
- `secret/homelab/elasticsearch/passwords`
- `secret/homelab/elasticsearch/api-keys`

Migrated credentials:
- CCHS_PASSWORD: [REDACTED]
- makerspace_es_api_key: [REDACTED]

**Verification:**
```bash
vault kv get secret/homelab/elasticsearch/passwords
vault kv get secret/homelab/elasticsearch/api-keys
```

**Note:** Original files `/Users/bret/git/homelab/CCHS_PASSWORD` and `/Users/bret/git/homelab/makerspace_es_api_key` should be deleted after git history sanitization.

### 2.5 Media Application Credentials Migration ✅
**Vault Paths:**
- `secret/homelab/apps/sonarr`
- `secret/homelab/apps/radarr`

Migrated credentials:
- Sonarr: api_key, url
- Radarr: api_key, url

**Verification:**
```bash
vault kv get secret/homelab/apps/sonarr
vault kv get secret/homelab/apps/radarr
```

**Configuration Files:**
- Created `/Users/bret/git/homelab/docker/docker-compose.yml.example` with Vault references

### 2.8 Network Configuration Migration ✅
**Vault Path:** `secret/homelab/network/config`

Migrated configuration:
- domain: lab.thewortmans.org
- gateway: 192.168.10.1
- dns_server: 192.168.10.1
- subnet: 192.168.10.0/24
- nfs_server: 192.168.1.230
- truenas_ip: 192.168.2.24

**Verification:**
```bash
vault kv get secret/homelab/network/config
```

### 2.9 Terraform Vault Integration ✅
**Files Updated:**
- `/Users/bret/git/homelab/tf/lab/versions.tf` - Added Vault provider requirement
- `/Users/bret/git/homelab/tf/lab/provider.tf` - Configured Vault provider and data sources
- `/Users/bret/git/homelab/tf/lab/variables.tf` - Removed sensitive defaults
- `/Users/bret/git/homelab/tf/lab/main.tf` - Updated to use Vault secrets

**Usage:**
```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN=$(vault login -token-only)
cd /Users/bret/git/homelab/tf/lab
terraform init
terraform plan
```

## Pending Tasks

### 2.6 Home Assistant and Pi-hole Credentials ⏳
**Action Required:**
- Identify current credentials in codebase
- Migrate to Vault paths:
  - `secret/homelab/home-assistant/config`
  - `secret/homelab/pihole/credentials`

### 2.7 Database Passwords and API Tokens ⏳
**Action Required:**
- Search codebase for database connection strings
- Identify all database passwords
- Migrate to appropriate Vault paths under respective service paths

### 2.10 Ansible Vault Integration ⏳
**Action Required:**
- Install `community.hashi_vault` Ansible collection
- Update playbooks in `/Users/bret/git/homelab/ansible/` to use Vault lookups
- Replace hardcoded credentials with Vault references
- Test playbook execution with Vault integration

### 2.11 Verify No Hardcoded Credentials Remain ⏳
**Files Identified with Hardcoded Credentials:**
```
./k8s/paperless/paperless.yaml:    adminPassword: "***REMOVED***"
./k8s/freenas-storageclass.yaml:    password: ***REMOVED***
./k8s/helm/values/freenas-nfs.yaml:        #password: ***REMOVED***
./k8s/helm/values/freenas-nfs.yaml:      password: "***REMOVED***"
./k8s/helm/values/prometheus.yaml:  adminPassword: ***REMOVED***
./k8s/helm/values/freenas-iscsi.yaml:      password: ***REMOVED***
./k8s/helm/values/freenas-iscsi.yaml:      # password: ***REMOVED***
./tf/scripts/setup-vault-secrets.sh:    password="***REMOVED***"
```

**Action Required:**
- Replace hardcoded passwords with Vault references
- Create .example files for each configuration
- Update original files to use VAULT_SECRET_REFERENCE placeholders

## Vault Secret Organization Structure

```
secret/homelab/
├── proxmox/terraform/          # Proxmox API credentials (COMPLETE)
├── freenas/
│   ├── credentials/            # TrueNAS API credentials (COMPLETE)
│   └── ssh/                    # SSH keys (COMPLETE)
├── elasticsearch/
│   ├── passwords/              # User passwords (COMPLETE)
│   └── api-keys/               # API keys (COMPLETE)
├── kubernetes/
│   ├── cluster/                # K3s tokens and certs (PENDING)
│   └── kubeconfig/             # Kubeconfig files (PENDING)
├── apps/
│   ├── sonarr/                 # Sonarr API key (COMPLETE)
│   ├── radarr/                 # Radarr API key (COMPLETE)
│   ├── plex/                   # Plex credentials (PENDING)
│   └── qbittorrent/            # qBittorrent credentials (PENDING)
├── home-assistant/config/      # Home Assistant credentials (PENDING)
├── pihole/credentials/         # Pi-hole admin password (PENDING)
├── databases/
│   ├── mysql/                  # Database passwords (PENDING)
│   └── postgresql/             # Database passwords (PENDING)
└── network/config/             # Network configuration values (COMPLETE)
```

## Next Steps

1. **Complete Pending Migrations (2.6, 2.7)**
   - Identify and migrate Home Assistant, Pi-hole, and database credentials

2. **Update Ansible Playbooks (2.10)**
   - Install required Ansible collections
   - Update playbooks to use Vault lookups
   - Test playbook execution

3. **Clean Up Hardcoded Credentials (2.11)**
   - Update identified files to use Vault references
   - Create .example files
   - Run comprehensive security scan

4. **Prepare for Git History Sanitization (Task Group 3)**
   - Verify all secrets are in Vault
   - Create backup branch
   - Run sanitization script in dry-run mode
   - Execute sanitization after approval

## Documentation References

- **Vault Setup:** `/Users/bret/git/homelab/docs/VAULT-SETUP.md`
- **Secret Management:** `/Users/bret/git/homelab/docs/SECRET-MANAGEMENT.md`
- **Vault Provider Example:** `/Users/bret/git/homelab/tf/vault-provider-example.tf`

## Security Notes

- All secrets migrated to Vault are stored with KV v2 engine (versioned)
- Vault is accessible at: https://192.168.10.101:8200
- TLS verification is disabled for self-signed certificates (development only)
- Production deployments should use proper CA-signed certificates
- Secret rotation schedule documented in SECRET-MANAGEMENT.md

## Testing Performed

All migrated secrets were verified using Vault CLI:
```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true
vault login  # Using root token

# Verified all secret paths
vault kv get secret/homelab/proxmox/terraform
vault kv get secret/homelab/freenas/credentials
vault kv get secret/homelab/freenas/ssh
vault kv get secret/homelab/elasticsearch/passwords
vault kv get secret/homelab/elasticsearch/api-keys
vault kv get secret/homelab/apps/sonarr
vault kv get secret/homelab/apps/radarr
vault kv get secret/homelab/network/config
```

All tests passed successfully.
