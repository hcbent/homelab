# MagicDNS Configuration

## Overview

This document describes the MagicDNS configuration for the Tailscale homelab migration.

**Tailnet Name:** shire-pangolin.ts.net
**Configuration Date:** 2025-11-18
**Status:** Configured

---

## MagicDNS Settings

| Setting | Value | Description |
|---------|-------|-------------|
| MagicDNS Enabled | Yes | Enables hostname resolution within tailnet |
| Tailnet Domain | shire-pangolin.ts.net | Base domain for all device hostnames |
| Override Local DNS | Yes | Tailscale DNS takes precedence for internal resolution |

---

## Internal Domain Convention

**Domain Pattern:** `*.home.lab`

All 18 homelab services will be accessible via the `home.lab` domain:

| Service | Internal URL | Backend Target |
|---------|-------------|----------------|
| Actual Budget | actual.home.lab | 192.168.10.250:5007 |
| ArgoCD | argocd.home.lab | kube.lb.thewortmans.org:8443 |
| CCHS Makerspace | makerspace.home.lab | bdwlb.myddns.me:7099 |
| CCHS Test | cchstest.home.lab | bdwlb.myddns.me:7098 |
| Cerebro | cerebro.home.lab | bdwlb.myddns.me:7008 |
| DF | df.home.lab | bdwlb.myddns.me:7042 |
| DFK | dfk.home.lab | bdwlb.myddns.me:7043 |
| Elasticsearch | elasticsearch.home.lab | bdwlb.myddns.me:7005 |
| Kibana | kibana.home.lab | bdwlb.myddns.me:7004 |
| Mealie | mealie.home.lab | 192.168.10.250:9925 |
| Monitoring (ES) | monitoring.home.lab | bdwlb.myddns.me:7009 |
| Paperless-ngx | paperless.home.lab | bdwlb.myddns.me:7007 |
| Pi-hole | pihole.home.lab | bdwlb.myddns.me:7012 |
| Plex | plex.home.lab | bdwlb.myddns.me:7100 |
| qBittorrent | qbittorrent.home.lab | kube.lb.thewortmans.org:8090 |
| Radarr | radarr.home.lab | 192.168.10.250:7878 |
| Sonarr | sonarr.home.lab | 192.168.10.250:8989 |

---

## DNS Records Created

### Tailscale Device Hostnames

| Device Name | Tailscale IP | FQDN |
|-------------|-------------|------|
| k8s-operator-homelab | 100.111.93.96 | k8s-operator-homelab.shire-pangolin.ts.net |
| brets-macbook-pro-2 | 100.70.154.57 | brets-macbook-pro-2.shire-pangolin.ts.net |

### Note on Kubernetes Nodes

Individual Kubernetes nodes (km01, km02, km03) do not appear in the Tailscale tailnet. The Tailscale Kubernetes operator handles routing to services within the cluster.

- **km01, km02, km03**: Accessed via local network (192.168.x.x)
- **Kubernetes services**: Exposed through the Tailscale operator
- **NGINX proxy**: Will route `*.home.lab` traffic to appropriate backends

---

## DNS Resolution Order

1. **Tailscale MagicDNS** - First priority for tailnet devices
   - Resolves `*.shire-pangolin.ts.net` hostnames
   - Handles device-to-device name resolution

2. **Split DNS (if configured)** - Second priority for internal domains
   - Can route `*.home.lab` to internal nameservers
   - Optional: Use Pi-hole or other local DNS

3. **External DNS** - Fallback for internet domains
   - Resolves all other domains (google.com, github.com, etc.)
   - Uses configured global nameservers

---

## Split DNS Configuration

### Current State

Split DNS for `home.lab` is **not required** for initial deployment.

The NGINX proxy (Task Group 4) will handle all `*.home.lab` routing:
- Clients connect to NGINX via its Tailscale hostname
- NGINX routes requests based on Host header
- No separate DNS server needed for `home.lab`

### Future Enhancement

If you want true split DNS (resolving `*.home.lab` directly):

1. **Option A: Use Pi-hole**
   - Add `home.lab` records in Pi-hole
   - Configure Tailscale to use Pi-hole for `home.lab` queries

2. **Option B: Use CoreDNS**
   - Deploy CoreDNS in Kubernetes
   - Expose via Tailscale operator
   - Configure split DNS to use CoreDNS for `home.lab`

---

## Global Nameservers

Configured external DNS servers for non-tailnet queries:

| Priority | Nameserver | Provider |
|----------|-----------|----------|
| Primary | 1.1.1.1 | Cloudflare |
| Secondary | 8.8.8.8 | Google |

---

## Testing Commands

### From a Tailscale-Connected Device

```bash
# Test MagicDNS resolution
ping k8s-operator-homelab.shire-pangolin.ts.net

# Check Tailscale status
tailscale status

# View DNS configuration (macOS)
scutil --dns | grep -A 5 "Tailscale"

# Test external DNS
nslookup google.com
```

### Expected Results

**MagicDNS Working:**
```
PING k8s-operator-homelab.shire-pangolin.ts.net (100.111.93.96)
64 bytes from 100.111.93.96: icmp_seq=0 ttl=64 time=XX ms
```

**External DNS Working:**
```
PING google.com (142.250.x.x)
64 bytes from 142.250.x.x: icmp_seq=0 ttl=XX time=XX ms
```

---

## Troubleshooting

### MagicDNS Not Resolving

1. Verify MagicDNS is enabled in admin console
2. Check device is connected: `tailscale status`
3. Restart Tailscale: `sudo killall tailscaled` (macOS)
4. Flush DNS cache: `sudo dscacheutil -flushcache` (macOS)

### External DNS Not Working

1. Check global nameservers in Tailscale admin
2. Verify "Override local DNS" setting
3. Test direct IP connectivity: `ping 8.8.8.8`

### Split DNS Issues

1. Verify split DNS configuration in admin console
2. Check internal nameserver is reachable
3. Test with: `nslookup <hostname> <nameserver-ip>`

---

## Related Documentation

- **Tailscale Organization Info**: `/Users/bret/git/homelab/tailscale/organization-info.txt`
- **ACL Policy**: `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
- **Task Group 3 Instructions**: `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-3-instructions.md`

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-11-18 | Initial MagicDNS configuration | Migration automation |
