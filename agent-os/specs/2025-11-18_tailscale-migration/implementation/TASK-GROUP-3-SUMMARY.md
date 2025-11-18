# Task Group 3: MagicDNS Configuration - Summary

## Status: READY FOR USER EXECUTION

## Overview

Task Group 3 configures MagicDNS for service discovery in the Tailscale tailnet. This establishes the DNS infrastructure that will route traffic to services via the `*.home.lab` domain pattern.

---

## Architecture Context

**Important:** The Tailscale Kubernetes operator (k8s-operator-homelab) is the only Kubernetes-related device in your tailnet. Individual nodes (km01, km02, km03) do NOT appear as separate Tailscale devices.

The `*.home.lab` service routing will work as follows:
1. Client resolves service hostname (e.g., `sonarr.home.lab`)
2. Request routes through Tailscale mesh to NGINX proxy
3. NGINX proxy routes to the appropriate backend service

---

## Implementation Files Created

| File | Purpose |
|------|---------|
| `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-3-instructions.md` | Step-by-step instructions for MagicDNS configuration |
| `/Users/bret/git/homelab/tailscale/magicdns-config.md` | Documentation of MagicDNS configuration and DNS records |
| `/Users/bret/git/homelab/tailscale/scripts/test-magicdns.sh` | Test script to verify DNS resolution |

---

## User Action Required

### Step 1: Connect Your MacBook to Tailscale

Your MacBook (brets-macbook-pro-2) appears to be offline. Connect it to Tailscale before proceeding with tests.

1. Open Tailscale app on your MacBook
2. Click Connect or toggle the connection on
3. Verify connection with: `tailscale status`

### Step 2: Verify MagicDNS Configuration

1. Navigate to: https://login.tailscale.com/admin/dns
2. Verify MagicDNS is enabled (toggle should be ON)
3. Verify "Override local DNS" is enabled
4. (Optional) Configure global nameservers if not already set

### Step 3: Test DNS Resolution

Run the test script from your MacBook:

```bash
cd /Users/bret/git/homelab/tailscale/scripts
./test-magicdns.sh
```

Or run individual test commands:

```bash
# Test MagicDNS resolution
ping -c 3 k8s-operator-homelab.shire-pangolin.ts.net

# Test by Tailscale IP
ping -c 3 100.111.93.96

# Verify external DNS still works
ping -c 3 google.com

# Check Tailscale status
tailscale status
```

### Step 4: Document Configuration

Update any configuration details in:
- `/Users/bret/git/homelab/tailscale/organization-info.txt`
- `/Users/bret/git/homelab/tailscale/magicdns-config.md`

---

## Expected Test Results

### Successful MagicDNS Test

```
Testing: Resolve k8s-operator-homelab.shire-pangolin.ts.net... PASS
Testing: Resolve k8s-operator-homelab (short name)... PASS
Testing: Ping 100.111.93.96 (direct IP)... PASS
Testing: Resolve google.com... PASS
Testing: Resolve github.com... PASS
Testing: Resolve cloudflare.com... PASS

Tests passed: 6/6
All tests passed! MagicDNS is working correctly.
```

### If Tests Fail

1. **MagicDNS not resolving:**
   - Verify MagicDNS is enabled in admin console
   - Restart Tailscale on your MacBook
   - Flush DNS cache: `sudo dscacheutil -flushcache`

2. **External DNS not working:**
   - Check global nameservers in Tailscale DNS settings
   - Verify internet connectivity

3. **Cannot reach K8s operator:**
   - Verify operator is running: check Tailscale admin machines page
   - Check operator pod in Kubernetes: `kubectl get pods -n tailscale-system`

---

## Configuration Summary

### MagicDNS Settings

| Setting | Value |
|---------|-------|
| MagicDNS Enabled | Yes |
| Tailnet Domain | shire-pangolin.ts.net |
| Override Local DNS | Yes |
| Internal Domain | *.home.lab |

### DNS Resolution Order

1. Tailscale MagicDNS (*.shire-pangolin.ts.net)
2. External DNS (google.com, etc.)

### Device Hostnames

| Device | Tailscale IP | FQDN |
|--------|-------------|------|
| k8s-operator-homelab | 100.111.93.96 | k8s-operator-homelab.shire-pangolin.ts.net |
| brets-macbook-pro-2 | 100.70.154.57 | brets-macbook-pro-2.shire-pangolin.ts.net |

---

## Note on Split DNS for home.lab

Split DNS configuration for `*.home.lab` is **not required** at this stage. The NGINX proxy (Task Group 4) will handle routing based on the Host header.

If you want true DNS resolution of `*.home.lab` names:
- This can be configured later using Pi-hole or CoreDNS
- For now, services will be accessed via the NGINX proxy hostname

---

## Acceptance Criteria Checklist

- [ ] MagicDNS enabled in Tailscale admin console
- [ ] Override local DNS enabled
- [ ] MacBook connected to Tailscale
- [ ] Can ping k8s-operator-homelab.shire-pangolin.ts.net
- [ ] Can resolve external domains (google.com, github.com)
- [ ] Test script passes all checks
- [ ] Documentation updated

---

## Next Steps

After completing Task Group 3:

1. **Task Group 4**: Deploy internal NGINX proxy to Kubernetes
   - NGINX will handle all `*.home.lab` routing
   - Will be exposed via Tailscale operator

2. **Task Group 5**: Service DNS Integration
   - Connect NGINX to Tailscale mesh
   - Configure `*.home.lab` service routing

---

## Files Reference

### Instructions
- `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-3-instructions.md`

### Configuration Documentation
- `/Users/bret/git/homelab/tailscale/magicdns-config.md`

### Test Script
- `/Users/bret/git/homelab/tailscale/scripts/test-magicdns.sh`

### Admin Console URLs
- DNS Settings: https://login.tailscale.com/admin/dns
- Machines: https://login.tailscale.com/admin/machines
