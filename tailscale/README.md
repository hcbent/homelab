# Tailscale Configuration for Homelab

This directory contains Tailscale configuration files and scripts for the homelab Kubernetes cluster and service mesh implementation.

## Directory Structure

```
tailscale/
├── README.md                           # This file
├── organization-info-template.txt      # Template for organization details
├── organization-info.txt               # Actual organization details (gitignored)
├── acl-policy-permissive.json         # Initial permissive ACL policy
├── scripts/
│   ├── store-auth-key.sh              # Store auth key in Vault
│   └── manage-funnel.sh               # Enable/disable Funnel (future)
└── kubernetes/                         # Kubernetes manifests (future)
    ├── operator/                       # Tailscale operator deployment
    └── services/                       # Service exposure configs
```

## Overview

This Tailscale implementation provides:

- **Zero-trust mesh networking** for all homelab services
- **Private access** to 16 services via Tailscale VPN
- **Public access** to 2 services via Tailscale Funnel
- **Clean URLs** using MagicDNS (*.home.lab)
- **Secure credential management** via HashiCorp Vault
- **Infrastructure-as-code** with version-controlled configurations

## Components

### 1. Auth Key Management

Auth keys are stored securely in HashiCorp Vault and never committed to git.

**Storage Path:** `secret/tailscale/auth-keys`

**Management Script:** `scripts/store-auth-key.sh`

### 2. ACL Policy

The ACL (Access Control List) policy defines who can access what in your tailnet.

**Initial Policy:** Permissive (all users can access all services)

**Policy File:** `acl-policy-permissive.json`

**Future Enhancement:** Granular per-service access controls after validation

### 3. Organization Configuration

Organization and tailnet details are documented in `organization-info.txt`.

**Template:** `organization-info-template.txt`

**Note:** The actual `organization-info.txt` should be created from the template and optionally added to `.gitignore` if it contains sensitive details.

## Setup Instructions

### Phase 1: Account and Auth Key Setup

1. **Document Organization Details**
   ```bash
   cp organization-info-template.txt organization-info.txt
   # Edit organization-info.txt with your Tailscale details
   ```

2. **Generate Auth Key**
   - Access Tailscale Admin Console: https://login.tailscale.com/admin
   - Navigate to Settings > Keys
   - Generate a reusable auth key with tags: `tag:kubernetes`, `tag:homelab`
   - Set expiration to 1 year

3. **Store Auth Key in Vault**
   ```bash
   ./scripts/store-auth-key.sh
   ```

4. **Apply ACL Policy**
   - Navigate to: https://login.tailscale.com/admin/acls
   - Copy contents of `acl-policy-permissive.json`
   - Paste into ACL editor and save

### Phase 2: Kubernetes Operator Deployment

See `kubernetes/operator/` directory for deployment manifests (created in Task Group 2).

### Phase 3: Service Exposure

See `kubernetes/services/` directory for service exposure configurations (created in Task Group 3).

## Services Configuration

### Private Services (16 total)

Access only via Tailscale mesh with *.home.lab URLs:

**Media Apps:**
- sonarr.home.lab
- radarr.home.lab
- qbittorrent.home.lab
- plex.home.lab

**Home Apps:**
- actual.home.lab
- mealie.home.lab
- paperless.home.lab
- pihole.home.lab

**Makerspace:**
- cchstest.home.lab
- makerspace.home.lab

**Elasticsearch Stack:**
- elasticsearch.home.lab
- cerebro.home.lab
- monitoring.home.lab (ES monitoring cluster)

**Other Services:**
- argocd.home.lab
- df.home.lab
- dfk.home.lab

### Public Services (2 total)

Access via both Tailscale Funnel (public) and Tailscale mesh (private):

- **kibana.bwortman.us** (also kibana.home.lab)
- **cchs.makerspace.hcbent.com** (also makerspace.home.lab)

## Security

### Auth Key Security

- Auth keys are stored encrypted in Vault
- Never committed to git
- Rotated annually or if compromised
- Access controlled via Vault policies

### ACL Policy Security

- Initial policy is permissive for validation
- Will be tightened after 2-week validation period
- Version-controlled in git
- Applied via Tailscale Admin Console

### Network Security

- Zero port forwarding on external firewall
- All traffic encrypted via WireGuard
- Private services inaccessible without Tailscale
- Public services protected by Tailscale Funnel SSL

## Vault Integration

### Vault Configuration

**Vault Address:** https://192.168.10.101:8200

**Vault Path:** `secret/tailscale/auth-keys`

**Vault Policy:** `tailscale-k8s`

### Retrieving Auth Key

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY="true"
vault login
vault kv get -field=auth_key secret/tailscale/auth-keys
```

### Vault Policy

The `tailscale-k8s` policy allows Kubernetes to read auth keys:

```hcl
path "secret/data/tailscale/auth-keys" {
  capabilities = ["read"]
}

path "secret/metadata/tailscale/auth-keys" {
  capabilities = ["read"]
}
```

## MagicDNS Configuration

MagicDNS provides automatic DNS resolution for tailnet devices and services.

**Internal Domain:** `*.home.lab`

**Configuration:**
- Enabled globally in Tailscale Admin Console
- DNS resolution order: Tailscale MagicDNS first, then external DNS
- All 18 services configured with *.home.lab hostnames

## Monitoring

Tailscale metrics will be integrated into the existing Prometheus/Grafana stack:

- Node connectivity status
- MagicDNS resolution health
- Funnel availability for public services
- Connection metrics and performance

See the monitoring configuration in the prometheus-stack setup.

## Future Enhancements

### Post-Validation (after 2 weeks)

1. **ACL Tightening**
   - Implement per-user access controls
   - Define service-specific access rules
   - Add time-based restrictions
   - Enable posture checks

2. **Funnel Management**
   - Script for on-demand Funnel enable/disable
   - Support for temporary service sharing
   - Quick disable procedures

3. **Advanced Features**
   - Tailscale SSH for node access
   - Exit nodes for internet routing
   - Subnet routers for network segments
   - Advanced monitoring and alerting

## Troubleshooting

### Auth Key Issues

**Problem:** Auth key not found in Vault

**Solution:**
```bash
./scripts/store-auth-key.sh
```

### ACL Policy Issues

**Problem:** ACL policy validation fails

**Solution:**
- Check JSON syntax
- Verify tag definitions in `tagOwners`
- Ensure all referenced hosts exist

### Connection Issues

**Problem:** Devices not appearing in tailnet

**Solution:**
- Verify auth key is correct
- Check Kubernetes operator logs
- Ensure nodes have internet connectivity
- Verify firewall rules allow UDP 41641

## Documentation References

- **Tailscale Documentation:** https://tailscale.com/kb
- **Kubernetes Operator:** https://tailscale.com/kb/1236/kubernetes-operator
- **ACL Policy:** https://tailscale.com/kb/1018/acls
- **MagicDNS:** https://tailscale.com/kb/1081/magicdns
- **Funnel:** https://tailscale.com/kb/1223/tailscale-funnel
- **Vault Documentation:** https://developer.hashicorp.com/vault/docs

## Support

For issues or questions:
- Check Tailscale status page: https://status.tailscale.com
- Review Kubernetes operator logs: `kubectl logs -n tailscale -l app=tailscale-operator`
- Consult homelab documentation: `agent-os/specs/2025-11-18_tailscale-migration/`

## Version History

- **2025-11-18:** Initial setup with Task Group 1 (auth keys, ACL policy)
- Future versions will be documented as features are added

## Contributing

All changes should:
1. Be tested in a non-production environment first
2. Follow infrastructure-as-code principles
3. Include documentation updates
4. Be version-controlled in git
5. Undergo peer review before production deployment
