# Task Group 3: MagicDNS Configuration Instructions

## Overview

This document provides step-by-step instructions for configuring MagicDNS for service discovery in your Tailscale tailnet (shire-pangolin.ts.net).

**Architecture Note:** The Tailscale Kubernetes operator (k8s-operator-homelab) is the only device that appears in your tailnet for Kubernetes. Individual nodes (km01, km02, km03) do not appear as separate devices. MagicDNS will be used to route traffic to the NGINX proxy (to be deployed in Task Group 4) which will handle routing to individual services.

## Prerequisites

- Task Group 2 complete (Tailscale operator deployed and connected)
- Access to Tailscale admin console: https://login.tailscale.com/admin
- Your MacBook connected to Tailscale (currently offline - needs reconnection)

---

## Task 3.1: Enable MagicDNS Globally

### Step-by-Step Instructions

1. **Access Tailscale Admin Console**
   - Navigate to: https://login.tailscale.com/admin
   - Log in with your credentials

2. **Navigate to DNS Settings**
   - Click on **"DNS"** in the left sidebar
   - You'll see the DNS settings page

3. **Enable MagicDNS**
   - Look for the **"MagicDNS"** toggle
   - If not already enabled, click to **enable** it
   - MagicDNS allows devices in your tailnet to resolve each other by hostname

4. **Verify MagicDNS is Active**
   - The toggle should show as enabled (blue/on)
   - You should see your tailnet name: `shire-pangolin.ts.net`
   - Devices will be resolvable as: `<hostname>.shire-pangolin.ts.net`

### Expected Result

After enabling MagicDNS:
- Devices in your tailnet can resolve each other by hostname
- The Kubernetes operator will be resolvable as: `k8s-operator-homelab.shire-pangolin.ts.net`

---

## Task 3.2: Configure Split DNS for home.lab Domain

### Important Context

Split DNS allows you to route DNS queries for specific domains to specific nameservers. For the `home.lab` domain, we'll configure Tailscale to route these queries to your internal NGINX proxy (once deployed).

**Note:** The actual `home.lab` domain routing will be fully functional after Task Group 4 (NGINX deployment). For now, we're setting up the DNS infrastructure.

### Step-by-Step Instructions

1. **Navigate to DNS Settings**
   - Go to: https://login.tailscale.com/admin/dns
   - Scroll down to find **"Nameservers"** section

2. **Add Custom DNS Nameservers (Optional)**
   - If you have a local DNS server (like Pi-hole), you can add it here
   - Click **"Add nameserver"**
   - Enter your Pi-hole IP or local DNS server
   - This ensures internal DNS queries are resolved locally

3. **Configure Split DNS for home.lab**

   **Option A: Using Tailscale's Built-in Split DNS**

   - Scroll to the **"Split DNS"** section
   - Click **"Add Split DNS"**
   - Enter the following:
     - **Domain:** `home.lab`
     - **Nameserver:** Enter the Tailscale IP of your Pi-hole or local DNS server
       - If using Pi-hole at `pihole.home.lab`, you'll need its Tailscale IP
       - Alternatively, use your router's DNS or a local DNS server
   - Click **"Save"**

   **Option B: Using Global Nameservers (Simpler Approach)**

   If you don't have a local DNS server for `home.lab`:
   - For now, skip split DNS configuration
   - The NGINX proxy (Task Group 4) will handle all `*.home.lab` routing
   - MagicDNS will resolve the NGINX proxy hostname
   - The NGINX proxy will route based on the Host header

4. **Set DNS Resolution Order**
   - In the DNS settings, ensure **"Override local DNS"** is enabled
   - This ensures Tailscale DNS takes precedence for internal domains
   - External domains (like google.com) will still resolve via external DNS

5. **Enable HTTPS DNS (Optional but Recommended)**
   - Enable **"DNS over HTTPS"** for additional privacy
   - This encrypts DNS queries to upstream resolvers

### Recommended Configuration for Your Setup

Since your architecture uses NGINX as the central routing point for `*.home.lab`:

1. **Enable MagicDNS** - Already done
2. **Enable "Override local DNS"** - Ensures Tailscale handles internal resolution
3. **Skip Split DNS for now** - Will be configured when NGINX is deployed
4. **Add global nameservers** (optional):
   - Primary: 1.1.1.1 (Cloudflare)
   - Secondary: 8.8.8.8 (Google)
   - Or use your ISP's DNS

---

## Task 3.3: Add DNS Records for Kubernetes Nodes

### Understanding the Architecture

**Important:** Individual Kubernetes nodes (km01, km02, km03) are NOT directly visible in your Tailscale tailnet. Only the Tailscale operator appears as a device.

However, you can add **custom records** or **aliases** in Tailscale to make these nodes accessible by friendly names.

### Option 1: Use Machine Hostnames in Admin Console

1. **View Connected Devices**
   - Go to: https://login.tailscale.com/admin/machines
   - You'll see: `k8s-operator-homelab` (100.111.93.96)

2. **Add Machine Aliases (if supported)**
   - Click on the `k8s-operator-homelab` device
   - Look for an option to add aliases or additional hostnames
   - This would allow resolving by different names

### Option 2: Use DNS Override Files (Advanced)

For advanced setups, you can configure local hosts or DNS overrides:

1. **On your MacBook**, add entries to `/etc/hosts`:
   ```bash
   # Tailscale homelab nodes (via operator)
   100.111.93.96 k8s-operator.home.lab
   ```

2. **Or use Pi-hole** to add local DNS records for your Kubernetes cluster:
   - Navigate to Pi-hole admin
   - Add custom DNS records pointing to your Kubernetes nodes' actual IPs
   - These would be local network IPs (192.168.x.x), not Tailscale IPs

### Current Device Inventory

| Device | Tailscale IP | Status |
|--------|-------------|--------|
| k8s-operator-homelab | 100.111.93.96 | Connected |
| brets-macbook-pro-2 | 100.70.154.57 | Needs Reconnection |

### What About km01, km02, km03?

These nodes are part of your local network (192.168.x.x) and are accessed through:
- **Direct IP**: 192.168.10.x for nodes
- **Kubernetes Load Balancer**: kube.lb.thewortmans.org
- **Dynamic DNS**: bdwlb.myddns.me

The Tailscale operator handles traffic routing to these services. You don't need individual Tailscale IPs for each node.

---

## Task 3.4: Test MagicDNS Resolution

### Prerequisites

Your MacBook needs to be connected to Tailscale. It was last seen at 10:34 AM EST and appears to be offline.

### Step 1: Connect Your MacBook to Tailscale

1. **Open Tailscale app** on your MacBook
   - Click the Tailscale icon in the menu bar
   - Click **"Connect"** or toggle the connection on

2. **Verify connection**
   - The icon should change to indicate connected status
   - Or run: `tailscale status`

### Step 2: Test MagicDNS Resolution

Once connected, run these tests from your MacBook terminal:

```bash
# Test 1: Ping the Kubernetes operator by Tailscale hostname
ping -c 3 k8s-operator-homelab.shire-pangolin.ts.net

# Test 2: Ping the Kubernetes operator by Tailscale IP
ping -c 3 100.111.93.96

# Test 3: Check Tailscale DNS resolution
nslookup k8s-operator-homelab.shire-pangolin.ts.net

# Test 4: Verify your MacBook is connected
tailscale status

# Test 5: Check DNS resolver configuration
scutil --dns | grep -A 5 "Tailscale"
```

### Step 3: Verify External DNS Still Works

```bash
# Test external DNS resolution
ping -c 3 google.com

# Test DNS lookup for external domain
nslookup google.com

# Test another external domain
ping -c 3 github.com
```

### Expected Results

**Successful MagicDNS Resolution:**
```
PING k8s-operator-homelab.shire-pangolin.ts.net (100.111.93.96): 56 data bytes
64 bytes from 100.111.93.96: icmp_seq=0 ttl=64 time=XX.XXX ms
...
```

**Successful External DNS:**
```
PING google.com (142.250.x.x): 56 data bytes
64 bytes from 142.250.x.x: icmp_seq=0 ttl=XX time=XX.XXX ms
...
```

### Troubleshooting

If MagicDNS isn't working:

1. **Check Tailscale connection**
   ```bash
   tailscale status
   ```
   Should show "Connected" and list devices

2. **Restart Tailscale**
   ```bash
   # On macOS
   sudo killall tailscaled
   # Then reconnect via the app
   ```

3. **Check DNS configuration**
   ```bash
   # View DNS resolvers
   scutil --dns
   ```

4. **Verify MagicDNS is enabled in admin console**
   - Go to https://login.tailscale.com/admin/dns
   - Ensure MagicDNS toggle is ON

---

## Task 3.5: Document MagicDNS Configuration

After completing the above tasks, update the documentation files with your configuration.

### Files to Update

1. **Organization Info** (`/Users/bret/git/homelab/tailscale/organization-info.txt`)
   - Confirm MagicDNS settings
   - Document any split DNS configuration

2. **MagicDNS Configuration Document** (created by this task group)
   - Path: `/Users/bret/git/homelab/tailscale/magicdns-config.md`

---

## Verification Checklist

Complete these checks after configuration:

- [ ] MagicDNS enabled in Tailscale admin console
- [ ] Override local DNS enabled
- [ ] MacBook connected to Tailscale
- [ ] Can ping k8s-operator-homelab.shire-pangolin.ts.net
- [ ] Can resolve external domains (google.com, github.com)
- [ ] Tailscale status shows both devices connected
- [ ] Documentation updated with configuration details

---

## Next Steps

After completing Task Group 3:

1. **Task Group 4**: Deploy internal NGINX proxy to Kubernetes
   - This will handle routing for all `*.home.lab` domains
   - NGINX will be exposed via the Tailscale operator

2. **Task Group 5**: Service DNS Integration
   - Configure MagicDNS to route `*.home.lab` to NGINX
   - Test end-to-end service access

---

## Support Resources

- **Tailscale DNS Documentation**: https://tailscale.com/kb/1054/dns
- **MagicDNS Documentation**: https://tailscale.com/kb/1081/magicdns
- **Split DNS Documentation**: https://tailscale.com/kb/1019/split-dns
- **Tailscale Admin Console**: https://login.tailscale.com/admin

---

## Summary

Task Group 3 establishes the DNS infrastructure for your Tailscale mesh network:

1. **MagicDNS** enables hostname resolution within the tailnet
2. **Split DNS** (optional) can route specific domains to internal nameservers
3. **DNS Records** for Kubernetes nodes are handled by the operator
4. **Testing** verifies both internal and external DNS resolution
5. **Documentation** captures all configuration for future reference

The actual `*.home.lab` service routing will be fully configured in Task Groups 4 and 5 when the NGINX proxy is deployed.
