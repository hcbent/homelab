# Task Group 4: NGINX Proxy Manager Deployment - Instructions

## Overview

This document provides instructions for completing the NGINX Proxy Manager deployment in Kubernetes with Tailscale exposure. Most of the automated work is complete - this document covers manual steps that require user interaction.

## Deployment Status

**Completed Automatically:**
- NPM namespace created
- PVCs created and bound (using freenas-iscsi-csi storage class)
- Deployment created and pod is running
- Service created with Tailscale annotations
- Tailscale operator has exposed NPM on the tailnet
- Pi-hole DNS updated to point *.home.lab to NPM's Tailscale IP
- ArgoCD application deployed and synced

**NPM Access Information:**
- **Tailscale IP:** 100.123.46.74
- **Tailscale Hostname:** npm.shire-pangolin.ts.net
- **Admin UI:** http://100.123.46.74:81 or http://npm.shire-pangolin.ts.net:81
- **HTTP Proxy:** http://100.123.46.74:80 or http://npm.shire-pangolin.ts.net:80
- **HTTPS Proxy:** https://100.123.46.74:443 (not used, but available)

## Manual Steps Required

### Step 1: Configure Admin Credentials

1. **Access NPM Admin UI:**
   - Open browser to: http://npm.shire-pangolin.ts.net:81
   - Or: http://100.123.46.74:81

2. **Login with default credentials:**
   - Email: admin@example.com
   - Password: changeme

3. **Change admin credentials:**
   - After login, click on your user icon (top right)
   - Select "Edit Details" or go to Users
   - Update email to your preferred email
   - Set a strong password
   - Save changes

### Step 2: Store Credentials in Vault

After changing credentials, store them securely in Vault:

```bash
# Connect to Vault
export VAULT_ADDR="https://vault.lab.thewortmans.org:8200"
export VAULT_TOKEN="<your-vault-token>"

# Store NPM admin credentials
vault kv put secret/nginx-proxy-manager/admin \
  email="<your-admin-email>" \
  password="<your-admin-password>"

# Verify storage
vault kv get secret/nginx-proxy-manager/admin
```

### Step 3: Configure Proxy Hosts

You need to add 17 proxy hosts to NPM for all the services. This must be done through the NPM admin UI.

**Access NPM Admin UI:** http://npm.shire-pangolin.ts.net:81

#### Configuration Settings (Apply to ALL hosts)

For each proxy host, use these settings:
- **Scheme:** http
- **SSL:** None (Tailscale handles encryption)
- **Websockets Support:** ON
- **Block Common Exploits:** ON

#### Proxy Hosts to Create

| Domain Name | Forward Hostname/IP | Forward Port |
|-------------|---------------------|--------------|
| actual.home.lab | 192.168.10.250 | 5007 |
| argocd.home.lab | kube.lab.thewortmans.org | 8443 |
| cerebro.home.lab | bdwlb.myddns.me | 7008 |
| cchstest.home.lab | bdwlb.myddns.me | 7098 |
| df.home.lab | bdwlb.myddns.me | 7042 |
| dfk.home.lab | bdwlb.myddns.me | 7043 |
| elasticsearch.home.lab | bdwlb.myddns.me | 7005 |
| kibana.home.lab | bdwlb.myddns.me | 7004 |
| makerspace.home.lab | bdwlb.myddns.me | 7099 |
| mealie.home.lab | 192.168.10.250 | 9925 |
| monitoring.home.lab | bdwlb.myddns.me | 7009 |
| paperless.home.lab | bdwlb.myddns.me | 7007 |
| pihole.home.lab | bdwlb.myddns.me | 7012 |
| plex.home.lab | bdwlb.myddns.me | 7100 |
| qbittorrent.home.lab | kube.lab.thewortmans.org | 8090 |
| radarr.home.lab | 192.168.10.250 | 7878 |
| sonarr.home.lab | 192.168.10.250 | 8989 |

#### Steps to Add Each Host

1. In NPM Admin UI, click **"Proxy Hosts"** in the sidebar
2. Click **"Add Proxy Host"**
3. **Details tab:**
   - Domain Names: Enter `<service>.home.lab` (e.g., `actual.home.lab`)
   - Scheme: `http`
   - Forward Hostname / IP: (from table above)
   - Forward Port: (from table above)
   - Check: **Websockets Support**
   - Check: **Block Common Exploits**
4. **SSL tab:** Leave disabled (no certificate needed)
5. Click **Save**
6. Repeat for all 17 services

### Step 4: Test End-to-End Access

After configuring all proxy hosts, test access from a Tailscale-connected device:

```bash
# Test actual.home.lab
curl -I http://actual.home.lab

# Test kibana.home.lab
curl -I http://kibana.home.lab

# Test argocd.home.lab
curl -I http://argocd.home.lab
```

Expected result: Each curl should return HTTP 200 or a redirect (301/302).

**Browser Testing:**
- Open http://actual.home.lab in browser
- Open http://kibana.home.lab in browser
- Verify services load correctly

### Step 5: Verify DNS Resolution

Test that Pi-hole DNS is correctly resolving *.home.lab to NPM:

```bash
# From any device using Pi-hole for DNS
nslookup actual.home.lab
# Expected: 100.123.46.74

nslookup kibana.home.lab
# Expected: 100.123.46.74

nslookup sonarr.home.lab
# Expected: 100.123.46.74
```

## Troubleshooting

### NPM Admin UI Not Accessible

1. Check pod is running:
   ```bash
   kubectl get pods -n nginx-proxy-manager
   ```

2. Check Tailscale proxy:
   ```bash
   kubectl get pods -n tailscale-system | grep npm
   ```

3. Verify Tailscale IP:
   ```bash
   kubectl exec -n tailscale-system ts-nginx-proxy-manager-pzczd-0 -- tailscale status
   ```

### DNS Not Resolving

1. Check Pi-hole configuration:
   ```bash
   ssh bret@192.168.10.53 "docker exec pihole cat /etc/pihole/pihole.toml | grep dnsmasq_lines"
   ```

2. Reload Pi-hole DNS:
   ```bash
   ssh bret@192.168.10.53 "docker exec pihole pihole reloaddns"
   ```

### Proxy Host Not Working

1. Verify the proxy host is configured correctly in NPM
2. Test direct connectivity to backend:
   ```bash
   curl -I http://192.168.10.250:5007  # for actual
   curl -I http://bdwlb.myddns.me:7004  # for kibana
   ```
3. Check NPM logs:
   ```bash
   kubectl logs -n nginx-proxy-manager -l app.kubernetes.io/name=nginx-proxy-manager
   ```

## Architecture Summary

```
User Device (Tailscale)
    |
    | (Tailscale mesh - encrypted)
    v
NPM Tailscale IP (100.123.46.74)
    |
    | ports 80/443/81
    v
NGINX Proxy Manager Pod (Kubernetes)
    |
    | (internal network)
    v
Backend Services
    - 192.168.10.250 (direct IP services)
    - kube.lab.thewortmans.org (K8s services)
    - bdwlb.myddns.me (DDNS services)
```

DNS Flow:
```
User queries actual.home.lab
    |
    v
Pi-hole (192.168.10.53)
    |
    | address=/home.lab/100.123.46.74
    v
Returns 100.123.46.74 (NPM Tailscale IP)
```

## Next Steps

After completing all proxy host configuration:

1. Task Group 5: Service DNS Integration
   - Verify all 18 services accessible via *.home.lab URLs
   - Document service catalog

2. Task Groups 6-9: Service Migration
   - Migrate services by category
   - Verify functionality after each migration

3. Task Group 10: Comprehensive Testing
   - Multi-device testing
   - Performance benchmarking
   - Security validation
