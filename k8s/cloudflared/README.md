# Cloudflare Tunnel (cloudflared)

Provides secure external access to internal services via Cloudflare's network without exposing ports.

## Architecture

```
Internet → Cloudflare Edge → cloudflared pod → NPM → Internal services
                             (outbound only)
```

## Setup Steps

### 1. Create Tunnel in Cloudflare

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to **Networks → Tunnels**
3. Click **Create a tunnel** → Select **Cloudflared**
4. Name it: `homelab-k8s`
5. Copy the tunnel token

### 2. Store Token in Vault

```bash
vault kv put secret/homelab/cloudflared tunnel_token="<YOUR_TUNNEL_TOKEN>"
```

### 3. Configure Tunnel Routes in Cloudflare

In the Cloudflare dashboard, configure the tunnel's **Public Hostname**:

| Subdomain | Domain | Service |
|-----------|--------|---------|
| `*` | `bwortman.us` | `http://nginx-proxy-manager.nginx-proxy-manager.svc:80` |

Or for specific services:
| Subdomain | Domain | Service |
|-----------|--------|---------|
| `npm` | `bwortman.us` | `http://nginx-proxy-manager.nginx-proxy-manager.svc:81` |
| `home` | `bwortman.us` | `http://nginx-proxy-manager.nginx-proxy-manager.svc:80` |

### 4. Deploy via ArgoCD

The `cloudflared-app.yaml` will deploy this automatically once External Secrets is configured.

## Replacing home.lab DNS

After cloudflared is working, you can:

1. **Option A**: Keep using `*.home.lab` internally, use `*.bwortman.us` externally
2. **Option B**: Migrate everything to `*.bwortman.us` and remove Pi-hole `home.lab` entry

## Dependencies

- External Secrets Operator (for Vault → K8s secret sync)
- Vault with `secret/homelab/cloudflared` containing `tunnel_token`
