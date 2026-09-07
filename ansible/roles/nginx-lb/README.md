# nginx-lb Role

Ansible role to deploy and manage NGINX load balancer configuration for Kubernetes NodePort services.

## Description

This role deploys NGINX configuration to load balance HTTP/HTTPS traffic across Kubernetes worker nodes for services exposed via NodePort. It's designed to work with the `nginx_proxy` inventory group.

## Requirements

- NGINX (will be installed by the role)
- Access to Kubernetes worker nodes
- NodePort services running in Kubernetes cluster

## Role Variables

### k8s_workers (required)
List of Kubernetes worker nodes with their IP addresses:
```yaml
k8s_workers:
  - name: kube01
    ip: 192.168.10.237
  - name: kube02
    ip: 192.168.10.238
  - name: kube03
    ip: 192.168.10.239
```

### services (required)
List of NodePort services to configure:
```yaml
services:
  - name: "mealie"
    description: "Mealie Recipe Manager (HTTP)"
    node_port: 32424        # NodePort on K8s
    listen_port: 9925       # Port nginx listens on
  - name: "sonarr"
    description: "Sonarr TV Management (HTTP)"
    node_port: 32220
    listen_port: 8989
```

### nginx_config (optional)
NGINX tuning parameters:
```yaml
nginx_config:
  lb_method: "least_conn"          # Load balancing method
  max_fails: 3                     # Health check failures before marking down
  fail_timeout: "30s"              # Time before retry after failure
  proxy_connect_timeout: "60s"     # Backend connection timeout
  proxy_send_timeout: "60s"        # Backend send timeout
  proxy_read_timeout: "60s"        # Backend read timeout
  health_check_port: 8080          # Health check endpoint port
  health_check_path: "/health"     # Health check path
```

### tautulli_service (optional)
Additional service configuration that can be added separately:
```yaml
tautulli_service:
  name: "tautulli"
  description: "Tautulli Media Stats (HTTP)"
  node_port: 31162
  listen_port: 8181
```

## Dependencies

None

## Example Playbook

```yaml
- name: Deploy NGINX Load Balancer
  hosts: nginx_proxy
  become: true

  roles:
    - role: nginx-lb
```

## Usage

Deploy the configuration:
```bash
ansible-playbook playbooks/deploy_nginx_lb.yml -i inventory/home
```

Check syntax before deploying:
```bash
ansible-playbook playbooks/deploy_nginx_lb.yml -i inventory/home --check
```

## Template

The role uses `templates/nginx-lb-http.conf.j2` which generates NGINX configuration with:

- Upstream definitions for each service pointing to all worker nodes
- Server blocks listening on specified ports
- Proper proxy headers (Host, X-Real-IP, X-Forwarded-For, etc.)
- WebSocket support
- Special handling for services that need custom headers (like qBittorrent)
- Health check endpoint

## Files Deployed

- `/etc/nginx/conf.d/nginx-lb-http.conf` - Main NGINX configuration for NodePort services

## Handlers

- `Reload NGINX` - Triggered when configuration changes

## Notes

- The role automatically includes all services defined in `services` plus `tautulli_service` if defined
- qBittorrent receives special header handling: `Host: localhost:8080`
- All other services receive: `Host: $host` (without port number)
- Configuration validates before reloading to prevent breaking NGINX

## License

MIT

## Author

Homelab Infrastructure Team
