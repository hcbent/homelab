# Task Group 4.5: Internal DNS Resolution for .home.lab Domains

## Problem Statement

Services need to reach each other using `.home.lab` addresses. For example:
- Cerebro (running on bdwlab.myddns.me:7008) needs to connect to elasticsearch at `es.home.lab` or `elasticsearch.home.lab`
- Other services may need similar internal service-to-service communication via `.home.lab` domains

Currently, `.home.lab` resolution only works from Tailscale-connected clients because:
1. Pi-hole DNS (on Tailscale network) resolves `*.home.lab` → 100.123.46.74 (NPM Tailscale IP)
2. Services NOT on Tailscale network cannot reach Pi-hole DNS
3. Services behind the old NGINX load balancer (bdwlab.myddns.me) have no way to resolve `.home.lab` domains

## Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Tailscale Network (100.x.x.x)                               │
│                                                              │
│  ┌──────────────┐         ┌─────────────────┐              │
│  │   Pi-hole    │         │  NPM (K8s)      │              │
│  │   DNS        │────────▶│  100.123.46.74  │              │
│  │              │         │  npm.shire-     │              │
│  └──────────────┘         │  pangolin.ts.net│              │
│        │                  └─────────────────┘              │
│        │ *.home.lab                                         │
│        │ → 100.123.46.74                                    │
└────────┼────────────────────────────────────────────────────┘
         │
         │ NO ACCESS
         ✗
┌────────┼────────────────────────────────────────────────────┐
│ LAN Network (192.168.10.x)                                  │
│        │                                                     │
│  ┌─────▼──────┐         ┌─────────────────┐                │
│  │  Cerebro   │         │ Elasticsearch   │                │
│  │  (wants to │─────✗──▶│ es.home.lab     │                │
│  │  connect)  │         │ (unreachable)   │                │
│  └────────────┘         └─────────────────┘                │
│  bdwlab.myddns.me:7008  bdwlab.myddns.me:7005              │
└─────────────────────────────────────────────────────────────┘
```

## Solution Options

### Option 1: Add Pi-hole as Secondary DNS for LAN Services (Recommended)

Configure the LAN services (or their host systems) to use Pi-hole as a secondary DNS server.

**Pros:**
- Simplest solution
- No infrastructure changes required
- Works for all services on the host

**Cons:**
- Requires configuration on each host running services
- Pi-hole must be accessible from LAN (already is via Tailscale subnet router)

**Implementation:**
1. Verify Pi-hole is accessible from LAN network
2. Update `/etc/resolv.conf` or network configuration on hosts running services:
   ```
   nameserver 192.168.10.x  # Primary LAN DNS
   nameserver 100.x.x.x     # Pi-hole on Tailscale
   ```
3. Test resolution: `dig @100.x.x.x es.home.lab`

### Option 2: Split DNS in Pi-hole for LAN Access

Configure Pi-hole to be accessible from LAN network and serve `.home.lab` queries.

**Pros:**
- Centralized DNS management
- Works for all devices on LAN

**Cons:**
- Requires Pi-hole to listen on LAN interface or be accessible via subnet router
- May have security implications

### Option 3: Add Local /etc/hosts Entries

Add static entries to `/etc/hosts` on each service host.

**Pros:**
- Dead simple
- No DNS infrastructure needed

**Cons:**
- Manual management per host
- Doesn't scale
- Must be updated when IPs change

### Option 4: Deploy CoreDNS in Kubernetes for Cross-Network DNS

Deploy a CoreDNS instance in Kubernetes that bridges Tailscale and LAN networks.

**Pros:**
- GitOps-managed
- Scalable
- Works for K8s pods and external services

**Cons:**
- Most complex solution
- Adds another DNS layer
- Overkill for current need

## Recommended Approach

**Option 1 + Option 3 Hybrid:**

1. For services running on physical/VM hosts (like cerebro on bdwlab):
   - Add Pi-hole as secondary DNS server
   - Use subnet router to access Pi-hole from LAN

2. For quick testing or temporary fixes:
   - Add `/etc/hosts` entries as needed

3. For future K8s-based services:
   - Use Kubernetes DNS (CoreDNS) with proper service discovery
   - Services in K8s will use internal service names

## Implementation Steps

### Step 1: Verify Pi-hole Accessibility from LAN

```bash
# From a LAN host (e.g., the host running cerebro)
dig @<pihole-tailscale-ip> es.home.lab
```

### Step 2: Configure Secondary DNS on Service Hosts

For the host running cerebro and other services on bdwlab:

```bash
# Check current DNS configuration
cat /etc/resolv.conf

# Add Pi-hole as secondary nameserver
# (Method depends on OS - systemd-resolved, NetworkManager, etc.)
```

### Step 3: Test Resolution

```bash
# From cerebro host
dig es.home.lab
curl -I http://es.home.lab/
```

### Step 4: Update Service Configurations

Update any hardcoded URLs in service configs to use `.home.lab` domains instead of direct IPs/hostnames.

## Testing Checklist

- [ ] Verify Pi-hole Tailscale IP is accessible from LAN
- [ ] Test DNS resolution of `.home.lab` from LAN host
- [ ] Verify cerebro can reach elasticsearch via `es.home.lab`
- [ ] Test other cross-service communication scenarios
- [ ] Document DNS configuration for future reference

## Questions to Answer

1. **Where is Pi-hole running?** (Need IP address)
2. **What OS are the services running on?** (affects DNS configuration method)
3. **Is there a subnet router configured?** (for Tailscale → LAN access)
4. **Do you want all LAN devices to use Pi-hole, or just specific service hosts?**
