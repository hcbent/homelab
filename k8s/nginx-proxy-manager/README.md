# NGINX Proxy Manager for Tailscale

This deployment provides NGINX Proxy Manager with Tailscale exposure for handling `*.home.lab` domains.

## Architecture

- **Purpose**: Reverse proxy for internal homelab services accessible via Tailscale
- **Exposure**: Via Tailscale operator annotation (`tailscale.com/expose: "true"`)
- **Hostname**: `npm.shire-pangolin.ts.net`
- **Ports**: 80 (HTTP), 443 (HTTPS), 81 (Admin UI)

## Deployment

### Via ArgoCD (Recommended)

```bash
kubectl apply -f /Users/bret/git/homelab/k8s/nginx-proxy-manager-app.yaml
```

### Manual Deployment

```bash
kubectl apply -f namespace.yaml
kubectl apply -f pvc.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```

## Post-Deployment Steps

### 1. Get Tailscale IP

After deployment, check the Tailscale admin console for NPM's IP:
- https://login.tailscale.com/admin/machines
- Look for "npm" device

Or via kubectl:
```bash
kubectl get svc nginx-proxy-manager -n nginx-proxy-manager -o jsonpath='{.metadata.annotations}'
```

### 2. Access Admin UI

```bash
# Get the Tailscale IP from admin console, then:
open http://<tailscale-ip>:81
```

Default credentials:
- Email: admin@example.com
- Password: changeme

**Change immediately and store in Vault:**
```bash
vault kv put secret/nginx-proxy-manager/admin \
  email="your-email" \
  password="your-secure-password"
```

### 3. Update Pi-hole DNS

Update Pi-hole to resolve `*.home.lab` to NPM's Tailscale IP:

```bash
# SSH to Pi-hole host
docker exec pihole sed -i 's/address=\/home.lab\/100.106.169.106/address=\/home.lab\/<NPM-TAILSCALE-IP>/' /etc/pihole/pihole.toml
docker exec pihole pihole restartdns
```

### 4. Configure Proxy Hosts

Add all 17 services from `/Users/bret/git/homelab/tailscale/home-lab-proxy-hosts.md`:

| Domain | Backend | Port |
|--------|---------|------|
| actual.home.lab | 192.168.10.250 | 5007 |
| kibana.home.lab | 192.168.10.40 | 5601 |
| sonarr.home.lab | 192.168.10.250 | 8989 |
| ... | ... | ... |

Settings for all:
- Scheme: http
- Websockets: ON
- Block Exploits: ON
- SSL: None (Tailscale handles encryption)

## Storage

Uses `tank` storage class (democratic-csi NFS provisioner):
- `nginx-proxy-manager-data`: 1Gi - SQLite database and config
- `nginx-proxy-manager-letsencrypt`: 1Gi - SSL certificates (future use)

## Troubleshooting

### Pod not starting
```bash
kubectl logs -n nginx-proxy-manager deployment/nginx-proxy-manager
kubectl describe pod -n nginx-proxy-manager -l app.kubernetes.io/name=nginx-proxy-manager
```

### Tailscale not exposing service
```bash
# Check Tailscale operator logs
kubectl logs -n tailscale-system deployment/tailscale-operator

# Verify service annotation
kubectl get svc nginx-proxy-manager -n nginx-proxy-manager -o yaml
```

### DNS not resolving
```bash
# Test from Tailscale-connected device
nslookup actual.home.lab
curl -I http://actual.home.lab
```

## Related Files

- ArgoCD Application: `/Users/bret/git/homelab/k8s/nginx-proxy-manager-app.yaml`
- Proxy hosts reference: `/Users/bret/git/homelab/tailscale/home-lab-proxy-hosts.md`
- Tailscale operator: `/Users/bret/git/homelab/k8s/tailscale/`
