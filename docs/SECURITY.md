# Security Best Practices

This document outlines the security architecture and best practices for this homelab infrastructure.

## Table of Contents

1. [Security Philosophy](#security-philosophy)
2. [Network Security](#network-security)
3. [Secret Management](#secret-management)
4. [Access Control](#access-control)
5. [Infrastructure Security](#infrastructure-security)
6. [Secret Scanning](#secret-scanning)
7. [TLS and Certificate Management](#tls-and-certificate-management)
8. [Pre-Public Checklist](#pre-public-checklist)
9. [Vulnerability Reporting](#vulnerability-reporting)
10. [Best Practices](#best-practices)

## Security Philosophy

This homelab follows a defense-in-depth security model with multiple layers:

- **Zero Secrets in Code**: All credentials stored in HashiCorp Vault
- **Network Segmentation**: VLAN isolation for different service tiers
- **Least Privilege**: Minimal permissions via Vault policies and Kubernetes RBAC
- **Audit Logging**: Comprehensive logging of secret access and infrastructure changes
- **Regular Rotation**: Automated credential rotation schedules
- **Secure by Default**: TLS encryption for all service communication

## Network Security

### VLAN Segmentation

The infrastructure uses VLAN isolation to separate different security zones:

```
Management VLAN (192.168.10.0/24)
├── Proxmox Hosts (192.168.10.1-9)
├── Kubernetes Control Plane (192.168.10.11-13)
├── Kubernetes Workers (192.168.10.14-16)
├── Elasticsearch Cluster (192.168.10.31-39)
└── Vault Server (192.168.10.101)

Application VLAN (192.168.20.0/24)
├── Media Services (Plex, *arr apps)
├── Home Automation (Home Assistant)
└── Network Services (Pi-hole)

Storage VLAN (192.168.2.0/24)
└── TrueNAS/FreeNAS (192.168.2.24)
```

### Firewall Rules

**Management VLAN**:
- Allow SSH (22/tcp) from admin workstations only
- Allow Kubernetes API (6443/tcp) from trusted networks
- Allow Vault API (8200/tcp) from infrastructure hosts only
- Deny internet access for control plane nodes

**Application VLAN**:
- Allow HTTP/HTTPS (80/tcp, 443/tcp) from LAN
- Allow service-specific ports (Plex: 32400, etc.)
- NAT for internet access (media downloads, updates)

**Storage VLAN**:
- Allow iSCSI (3260/tcp) from Kubernetes nodes only
- Allow NFS (2049/tcp) from Kubernetes nodes only
- Allow TrueNAS API (443/tcp) from management network only
- Deny all other traffic

### Network Isolation Strategy

1. **Infrastructure Isolation**: Management VLAN separated from application traffic
2. **Storage Isolation**: Dedicated VLAN for storage traffic (iSCSI/NFS)
3. **Service Boundaries**: Each service tier in isolated namespace/network segment
4. **Ingress Control**: Single ingress point via Traefik with TLS termination
5. **Egress Filtering**: Outbound traffic restricted by firewall rules

## Secret Management

All secrets are managed through HashiCorp Vault. See [SECRET-MANAGEMENT.md](SECRET-MANAGEMENT.md) for detailed usage.

### Vault Security Model

- **Encryption at Rest**: All secrets encrypted with AES-256-GCM
- **Encryption in Transit**: TLS 1.2+ for all Vault API communication
- **Unsealing**: Manual unsealing with 3-of-5 Shamir keys (auto-unseal for production)
- **Access Control**: Fine-grained policies for service authentication
- **Audit Logging**: All secret access logged for compliance

### Secret Organization

Secrets organized by service boundaries:

```
secret/homelab/
├── proxmox/        # Infrastructure credentials
├── freenas/        # Storage credentials
├── kubernetes/     # Cluster secrets
├── elasticsearch/  # Logging credentials
├── apps/           # Application secrets
└── databases/      # Database passwords
```

See [VAULT-SETUP.md](VAULT-SETUP.md#secret-organization) for complete structure.

### Credential Rotation Schedule

| Secret Type | Rotation Frequency | Method |
|-------------|-------------------|--------|
| Root passwords | 90 days | Manual via script |
| API keys | 90 days | Automated via Vault |
| Service tokens | 180 days | Automated via Vault |
| SSH keys | 365 days | Manual rotation |
| TLS certificates | 365 days (self-signed) | Automated renewal |

**Rotation Script**: `/Users/bret/git/homelab/vault/scripts/04-rotate-credentials.sh`

### Zero Secrets in Code

**Enforcement Mechanisms**:
1. `.gitignore` patterns for secret files (`*_PASSWORD`, `*_TOKEN`, `*_API_KEY`, `.env`)
2. Pre-commit hooks with detect-secrets (Phase 2)
3. GitHub Actions secret scanning (Phase 2)
4. `.example` file pattern for all sensitive configurations

**Example Pattern**:
```bash
# Real file (gitignored)
config.yaml

# Template (committed)
config.yaml.example
```

See [README.md - Using Example Files](../README.md#using-example-files) for usage.

## Access Control

### SSH Access

**Key-Based Authentication Only**:
- Password authentication disabled on all hosts
- Ed25519 keys required (minimum 256-bit)
- Keys rotated annually
- Separate keys for different access levels

**SSH Configuration** (`/etc/ssh/sshd_config`):
```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
```

### Vault Access Control

**Authentication Methods**:
- **Token Auth**: Short-lived tokens with TTL (1-24 hours)
- **Userpass Auth**: Service accounts for automation (Terraform, Ansible)
- **Kubernetes Auth**: Pod-level service account authentication (via External Secrets)

**Policy Examples**:

```hcl
# Terraform - read-only access to infrastructure secrets
path "secret/data/homelab/proxmox/*" {
  capabilities = ["read", "list"]
}

# Ansible - read access to configuration secrets
path "secret/data/homelab/elasticsearch/*" {
  capabilities = ["read", "list"]
}

# Applications - read-only access to app-specific secrets
path "secret/data/homelab/apps/plex" {
  capabilities = ["read"]
}
```

### Kubernetes RBAC

**Service Accounts**:
- Namespace-isolated service accounts
- Minimal ClusterRole/Role bindings
- No default service account token mounting

**Example RBAC**:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: app-reader
  namespace: media
rules:
- apiGroups: [""]
  resources: ["secrets", "configmaps"]
  verbs: ["get", "list"]
```

### Proxmox Access

- **API User**: Dedicated `terraform@pve` user with minimal permissions
- **Token Authentication**: API tokens instead of passwords where possible
- **Audit Logging**: All API calls logged in Proxmox audit log

## Infrastructure Security

### Proxmox Hardening

1. **Network Security**:
   - Management interface on isolated VLAN
   - Firewall enabled on all hosts
   - VMs use separate networks

2. **Authentication**:
   - Multi-factor authentication enabled
   - Separate users for automation vs. interactive access
   - API tokens with restricted permissions

3. **VM Security**:
   - Cloud-init for automated provisioning
   - No default passwords in templates
   - SSH keys injected at VM creation
   - Automated security updates via Ansible

### TrueNAS/FreeNAS Hardening

1. **API Security**:
   - API keys stored in Vault only
   - TLS required for all API calls
   - API access restricted to management VLAN

2. **Storage Security**:
   - iSCSI CHAP authentication
   - NFS exports restricted by IP/network
   - Dataset-level encryption for sensitive data
   - Regular ZFS snapshots for recovery

3. **SSH Access**:
   - Root SSH disabled
   - Key-based authentication required
   - Separate SSH keys for automation

### Kubernetes Cluster Hardening

1. **Control Plane Security**:
   - API server authentication required
   - RBAC enabled (default deny)
   - Admission controllers enabled
   - Audit logging enabled

2. **Node Security**:
   - SELinux/AppArmor enabled
   - No privileged containers unless explicitly allowed
   - PodSecurityPolicy/Pod Security Standards enforced
   - Regular node security updates

3. **Network Policies**:
   - Default deny ingress/egress
   - Namespace isolation
   - Service mesh for encrypted pod-to-pod communication

4. **Secret Management**:
   - External Secrets Operator syncs from Vault
   - No secrets in manifests
   - Secrets encrypted at rest in etcd

See [EXTERNAL-SECRETS-SETUP.md](EXTERNAL-SECRETS-SETUP.md) for configuration.

## Secret Scanning

### Pre-Commit Hooks (Phase 2)

Prevent secret commits at development time:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

**Setup**:
```bash
cd /Users/bret/git/homelab
./scripts/setup-pre-commit.sh
```

### GitHub Actions Secret Scanning (Phase 2)

Automated scanning on every PR and push:

**Workflow**: `.github/workflows/secret-scan.yml`
- Runs gitleaks on all commits
- Fails PR if secrets detected
- Custom rules for homelab-specific patterns
- Allowlist for false positives (.example files)

### Manual Secret Scanning

Scan entire repository history:

```bash
# Using gitleaks
gitleaks detect --source /Users/bret/git/homelab --verbose

# Using git-secrets
git secrets --scan

# Using grep for specific patterns
grep -r "password\|api_key\|token\|secret" \
  --exclude-dir=.git \
  --exclude="*.example" \
  /Users/bret/git/homelab
```

### Git History Sanitization

Remove secrets from git history before making repository public.

See [SANITIZING-GIT-HISTORY.md](SANITIZING-GIT-HISTORY.md) for complete guide.

**Quick Process**:
```bash
# 1. Backup
git branch backup/pre-sanitization-$(date +%Y%m%d)

# 2. Dry run
./scripts/sanitize-git-history.sh --dry-run

# 3. Execute
./scripts/sanitize-git-history.sh

# 4. Verify
gitleaks detect --source . --verbose
```

## TLS and Certificate Management

### Internal Certificate Authority

Use step-certificates for internal CA:

```bash
# Install step-ca
kubectl apply -f k8s/step-certificates/

# Create internal certificates
step certificate create example.lab.thewortmans.org \
  example.crt example.key \
  --ca ~/.step/certs/root_ca.crt \
  --ca-key ~/.step/secrets/root_ca_key
```

### Vault TLS Configuration

**Self-Signed Certificate** (development):
```bash
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout vault.key -out vault.crt \
  -subj "/CN=vault.lab.thewortmans.org"
```

**Production**: Use proper CA-signed certificate from Let's Encrypt or internal CA.

### Service Certificates

- **Proxmox**: Self-signed or Let's Encrypt via ACME
- **Kubernetes Ingress**: cert-manager with Let's Encrypt or step-certificates
- **Elasticsearch**: Self-signed or step-certificates
- **Applications**: TLS termination at Traefik ingress

## Pre-Public Checklist

Before making this repository public, verify all security measures:

### Secret Removal Checklist

- [ ] All secrets migrated to Vault
- [ ] No hardcoded credentials in code
- [ ] Git history sanitized (run script)
- [ ] Secret scanning passed (gitleaks clean)
- [ ] All .example files reviewed
- [ ] No sensitive data in comments or docs

### Access Control Checklist

- [ ] Vault unsealed and accessible
- [ ] Vault policies configured
- [ ] All service accounts created
- [ ] SSH keys rotated
- [ ] API tokens secured in Vault

### Network Security Checklist

- [ ] Firewall rules configured
- [ ] VLANs properly segmented
- [ ] Internal services not exposed to internet
- [ ] DNS properly configured

### Documentation Checklist

- [ ] No internal IPs exposed unnecessarily
- [ ] No personal information in docs
- [ ] All setup guides complete
- [ ] Security best practices documented

### Verification Checklist

- [ ] Clean clone test completed
- [ ] External user can follow documentation
- [ ] All .example files work as templates
- [ ] Secret scanning workflow active (Phase 2)

See [PRE-PUBLIC-CHECKLIST.md](PRE-PUBLIC-CHECKLIST.md) for complete verification process.

## Vulnerability Reporting

If you discover a security vulnerability in this repository:

### Reporting Process

1. **DO NOT** open a public GitHub issue
2. Email security concerns to: [Contact via GitHub private message]
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Resolution Plan**: Within 14 days
- **Fix Deployment**: Depends on severity (critical: immediate, high: 7 days, medium: 30 days)

### Disclosure Policy

- Coordinated disclosure preferred
- 90-day disclosure timeline from report
- Credit given to reporter (if desired)
- Security advisory published after fix

## Best Practices

### Development Practices

1. **Never Commit Secrets**:
   - Use .example files
   - Reference Vault paths in comments
   - Run secret scanning before commits

2. **Use Environment-Specific Configs**:
   - Separate configs for dev/staging/production
   - Store environment values in Vault
   - Use Terraform workspaces or separate state

3. **Principle of Least Privilege**:
   - Minimal Vault policies
   - Minimal Kubernetes RBAC
   - Minimal API permissions

4. **Defense in Depth**:
   - Network segmentation
   - Service isolation
   - Multiple authentication layers

### Operational Practices

1. **Regular Updates**:
   - Security patches within 7 days
   - OS updates monthly
   - Application updates quarterly

2. **Backup Strategy**:
   - Vault data backed up weekly
   - Kubernetes etcd backed up daily
   - Configuration files in version control

3. **Monitoring and Alerting**:
   - Vault audit logs monitored
   - Kubernetes events monitored
   - Failed authentication attempts alerted

4. **Incident Response**:
   - Document security incidents
   - Rotate compromised credentials immediately
   - Review and update security measures

### Secret Management Practices

1. **Rotation Schedule**:
   - Follow credential rotation schedule
   - Automate where possible
   - Document manual rotation procedures

2. **Access Auditing**:
   - Review Vault audit logs monthly
   - Revoke unused tokens
   - Review service account permissions quarterly

3. **Secret Lifecycle**:
   - Create secrets with minimal TTL
   - Revoke on service decommission
   - Rotate on personnel changes

4. **Documentation**:
   - Document all Vault paths
   - Keep secret organization up to date
   - Document emergency access procedures

### Network Security Practices

1. **Firewall Management**:
   - Default deny all traffic
   - Explicit allow rules only
   - Regular firewall rule audits

2. **Network Monitoring**:
   - Monitor for unauthorized connections
   - Log all firewall denials
   - Alert on suspicious traffic patterns

3. **Service Exposure**:
   - Minimize internet-facing services
   - Use VPN for remote access
   - TLS for all external services

## Security Maintenance

### Daily Tasks

- Monitor security alerts
- Review failed authentication attempts
- Check Vault unsealed status

### Weekly Tasks

- Review Vault audit logs
- Backup Vault data
- Update security documentation

### Monthly Tasks

- Patch security vulnerabilities
- Review and rotate credentials per schedule
- Audit firewall rules
- Review service account permissions

### Quarterly Tasks

- Conduct security assessment
- Review and update security policies
- Update documentation
- Test disaster recovery procedures

### Annual Tasks

- Rotate SSH keys
- Renew TLS certificates
- Comprehensive security audit
- Update security training

## References

- [HashiCorp Vault Security Model](https://www.vaultproject.io/docs/internals/security)
- [Kubernetes Security Best Practices](https://kubernetes.io/docs/concepts/security/security-best-practices/)
- [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)

## Related Documentation

- [Vault Setup Guide](VAULT-SETUP.md) - Complete Vault installation and configuration
- [Secret Management Guide](SECRET-MANAGEMENT.md) - Vault usage patterns and integration
- [Sanitizing Git History](SANITIZING-GIT-HISTORY.md) - Remove secrets from repository
- [External Secrets Setup](EXTERNAL-SECRETS-SETUP.md) - Kubernetes secret automation
- [Pre-Public Checklist](PRE-PUBLIC-CHECKLIST.md) - Verification before public release
- [Deployment Guide](DEPLOYMENT-GUIDE.md) - Complete deployment workflow
