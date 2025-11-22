# Task Group 4.5: Internal DNS Resolution Implementation

## Problem Solved

Kubernetes pods need to resolve `.home.lab` domains to reach services via NGINX Proxy Manager.

**Example use case:** Cerebro (when deployed in K8s) needs to connect to elasticsearch at `elasticsearch.home.lab`

## Solution: CoreDNS Forwarding to Pi-hole

Configure Kubernetes CoreDNS to forward all `.home.lab` queries to Pi-hole at `192.168.10.53`.

## Implementation

### Configuration File

Created: `/Users/bret/git/homelab/k8s/coredns-custom-config.yaml`

This ConfigMap adds a new DNS zone handler for `home.lab` that forwards to Pi-hole, while keeping all other DNS queries going to the router (192.168.10.1).

### DNS Flow After Implementation

```
┌────────────────────────────────────────────────────────────┐
│ Kubernetes Pod (e.g., cerebro)                             │
│                                                             │
│  "What is elasticsearch.home.lab?"                         │
└─────────────────┬──────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ CoreDNS (kube-system)                                        │
│                                                              │
│  *.home.lab? ──────▶ Forward to 192.168.10.53 (Pi-hole)    │
│  Other queries? ───▶ Forward to 192.168.10.1 (Router)      │
└─────────────────┬────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Pi-hole (192.168.10.53)                                     │
│                                                              │
│  *.home.lab ──────▶ 100.123.46.74 (NPM on Tailscale)       │
└─────────────────┬────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ NGINX Proxy Manager (npm.shire-pangolin.ts.net)            │
│                                                              │
│  elasticsearch.home.lab ──▶ bdwlab.myddns.me:7005          │
│  cerebro.home.lab ──────────▶ cerebro.cerebro.svc:9000     │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Steps

1. **Apply the CoreDNS configuration:**
   ```bash
   kubectl apply -f /Users/bret/git/homelab/k8s/coredns-custom-config.yaml
   ```

2. **Restart CoreDNS pods to pick up the new configuration:**
   ```bash
   kubectl rollout restart deployment coredns -n kube-system
   ```

3. **Wait for CoreDNS pods to be ready:**
   ```bash
   kubectl rollout status deployment coredns -n kube-system
   ```

4. **Test DNS resolution from a pod:**
   ```bash
   # Create a test pod
   kubectl run dnstest --image=busybox:1.28 --rm -it --restart=Never -- nslookup elasticsearch.home.lab
   ```

   Expected output should show `elasticsearch.home.lab` resolving to `100.123.46.74` (NPM's Tailscale IP).

### Verification

After deployment, verify that:

- [ ] CoreDNS pods restarted successfully
- [ ] `.home.lab` domains resolve from within K8s pods
- [ ] Non `.home.lab` domains still resolve normally
- [ ] Cerebro (when deployed) can reach elasticsearch via `elasticsearch.home.lab`

### Testing Commands

```bash
# Test from a temporary pod
kubectl run dnstest --image=busybox:1.28 --rm -it --restart=Never -- sh -c "nslookup elasticsearch.home.lab && nslookup google.com"

# Expected results:
# elasticsearch.home.lab → 100.123.46.74 (via Pi-hole)
# google.com → <public IP> (via router)
```

### Rollback

If issues occur, revert to original configuration:

```bash
kubectl get configmap coredns -n kube-system -o yaml > /tmp/coredns-backup.yaml
# Edit to remove home.lab section
kubectl apply -f /tmp/coredns-backup.yaml
kubectl rollout restart deployment coredns -n kube-system
```

## Benefits

1. **Kubernetes pods can reach external services via .home.lab domains**
2. **No per-pod configuration needed** - works cluster-wide
3. **Centralized DNS management** via Pi-hole
4. **Maintains existing DNS behavior** for non-.home.lab queries
5. **GitOps-ready** - configuration in version control

## Next Steps

After this is deployed and verified:
- Deploy cerebro to Kubernetes
- Configure cerebro to connect to `elasticsearch.home.lab` (or `es.home.lab`)
- Add cerebro proxy host to NPM pointing to the K8s service
