# Specification: Tailscale Migration

## Goal
Migrate homelab infrastructure from Cloudflare DNS + NGINX Proxy Manager to Tailscale-based zero-trust mesh networking, providing secure private access to 16 services and maintaining public access for 2 services via Tailscale Funnel.

## User Stories
- As a homelab user, I want to access all services securely without exposing ports on my firewall so that my attack surface is minimized
- As an administrator, I want clean URLs (*.home.lab) instead of IP:port combinations so that services are easier to remember and access

## Specific Requirements

**Tailscale Kubernetes Operator Deployment**
- Deploy Tailscale Kubernetes operator across 3-node cluster (km01, km02, km03)
- Use NodePort service type per project standard
- Retrieve Tailscale auth keys from Vault at secret/tailscale/auth-keys
- Configure reusable, tagged auth keys for Kubernetes nodes
- Ensure all nodes appear in tailnet with proper hostnames
- Follow existing RBAC patterns from nginx-ingress.yaml (ServiceAccount, ClusterRole, ClusterRoleBinding)
- Apply resource requests and limits similar to existing deployments
- Configure liveness and readiness probes for health monitoring

**MagicDNS Configuration**
- Configure MagicDNS globally in Tailscale admin console
- Set internal domain to *.home.lab for all 18 services
- Ensure DNS resolution order: Tailscale MagicDNS for internal domains, external DNS for internet
- Validate DNS resolution from all Tailscale-connected devices
- Configure MagicDNS to resolve NGINX proxy hostname for service routing

**Internal NGINX Proxy Deployment**
- Deploy standard NGINX (not NGINX Proxy Manager) to Kubernetes cluster
- Use ConfigMap-based configuration approach following nginx-ingress.yaml pattern
- Create 18 upstream definitions: 4 direct IP (192.168.10.250), 2 Kubernetes LB (kube.lb.thewortmans.org), 12 dynamic DNS (bdwlb.myddns.me)
- Configure 18 server blocks for *.home.lab domains with basic proxy_pass directives
- Set proxy headers: Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto
- Deploy as NodePort service for external accessibility
- Start with minimal configuration - defer advanced features (connection pooling, health checks, failover) to future phase
- HTTP only (no SSL/TLS) - encryption handled by Tailscale mesh

**Permissive ACL Policy Initial Configuration**
- Start with permissive "all users can access all services" ACL policy in Tailscale admin console
- Ensure no service access breaks during migration
- Document ACL structure for future tightening post-validation
- Plan to incrementally restrict access after 2-week validation period

**Public Service Funnel Configuration (2 services)**
- Configure permanent Tailscale Funnel for kibana.bwortman.us (bdwlb.myddns.me:7004)
- Configure permanent Tailscale Funnel for cchs.makerspace.hcbent.com (bdwlb.myddns.me:7099)
- Provide dual access: public via Funnel AND private via Tailscale mesh
- Automatic HTTPS certificate management via Tailscale (*.ts.net domains)
- Update DNS records: CNAME to Tailscale Funnel endpoints
- Lower DNS TTL to 300 seconds 24 hours before cutover
- Validate SSL certificates and public accessibility without Tailscale connection

**Private Service Migration (16 services)**
- Media apps: sonarr, radarr, qbittorrent, plex
- Home apps: actual, mealie, paperless, pihole
- Makerspace: cchstest, makerspace (alias)
- Elasticsearch stack: elasticsearch, cerebro, monitoring (ES monitoring cluster)
- Other: argocd, df, dfk
- All accessible only via Tailscale mesh with *.home.lab URLs
- No public DNS records - services become private-only
- Remove Let's Encrypt certificates (no longer needed)

**On-Demand Funnel Management Script**
- Create shell script to enable/disable Funnel for any service temporarily
- Script should accept service name and action (enable/disable) parameters
- Validate Funnel is properly enabled/disabled with status check
- Document single-user temporary sharing use case (e.g., sharing Plex for one evening)
- Ensure clean disable procedure after sharing period
- Target execution time under 5 minutes for enable/disable workflow

**Monitoring and Observability Integration**
- Integrate Tailscale metrics into existing Prometheus stack
- Monitor: node connectivity status, MagicDNS resolution health, Funnel availability
- Create dedicated Grafana dashboard for Tailscale mesh health visualization
- Configure Prometheus alerts for node disconnections and Funnel unavailability
- Feed Tailscale audit logs to Elasticsearch for access pattern analysis
- Create Kibana dashboards for Tailscale access visualization
- Monitor all 18 services including ES monitoring cluster at monitoring.home.lab

**Testing and Validation Strategy**
- Test from multiple device types: laptop (macOS/Windows/Linux), phone (iOS/Android), tablet
- Test from multiple network locations: home WiFi, cellular (4G/5G), remote networks
- Verify MagicDNS resolution for all 18 *.home.lab domains
- Test all service functionality end-to-end (service-specific validations)
- Performance benchmarking: page load times, media streaming quality, file transfers, API response times
- Public service validation: kibana and cchs.makerspace accessible without Tailscale
- Funnel on-demand workflow testing: enable, verify public access, disable, verify access removed
- 2-week soak period with monitoring before infrastructure decommission

**Infrastructure Cleanup and Rollback**
- Maintain 90-day rollback capability with archived configurations
- Export NGINX Proxy Manager configuration for reference
- Remove port forwarding rules from router/firewall
- Deprecate DNS records for 16 private services in Cloudflare
- Maintain DNS records for 2 public services (point to Funnel)
- Archive old configuration files, DNS records, port forwarding rules
- Document rollback procedures valid for 90 days
- Verify zero external ports open via nmap scan
- Update infrastructure documentation and network diagrams

**Phase 0 Critical Blocker: Prometheus/Grafana Verification**
- MUST verify prometheus-stack ArgoCD application is deployed and synced before any other work
- Check ArgoCD app status: kubectl get application prometheus-stack -n argocd
- If not deployed, apply prometheus-stack-app.yaml to ArgoCD
- Verify Prometheus is accessible and collecting metrics
- Verify Grafana is accessible with functional dashboards
- Confirm monitoring pipeline ready to accept Tailscale metrics
- This is a HARD BLOCKER - do not proceed until monitoring operational

## Visual Design
No visual assets provided.

## Existing Code to Leverage

**NGINX Ingress Controller (/Users/bret/git/homelab/k8s/basement/nginx-ingress.yaml)**
- ConfigMap-based configuration pattern for NGINX settings
- ServiceAccount + ClusterRole + ClusterRoleBinding RBAC structure
- Deployment with liveness/readiness health probes
- NodePort service type standard
- Resource requests/limits definitions (cpu: 100m-500m, memory: 200Mi-500Mi)
- Use ingress-nginx controller v1.10.0 as reference version

**Vault Deployment (/Users/bret/git/homelab/k8s/basement/vault-deployment.yaml)**
- StatefulSet pattern for stateful services if Tailscale requires persistence
- ConfigMap for application configuration (vault.hcl pattern)
- ServiceAccount with ClusterRole/ClusterRoleBinding RBAC
- Security context configuration (runAsNonRoot, runAsUser, runAsGroup, fsGroup)
- Resource requests/limits best practices (cpu: 200m-500m, memory: 1Gi-2Gi)
- PersistentVolumeClaim with storageClassName pattern

**qBittorrent Service (/Users/bret/git/homelab/k8s/media/qbittorrent-values.yaml)**
- bjw-s app-template Helm chart pattern (could be used for Tailscale)
- NodePort service type (project standard)
- Lifecycle hooks for post-start configuration (useful for Tailscale post-deployment setup)
- Health probes configuration (liveness/readiness)
- Persistent storage with multiple volumes (iSCSI + NFS patterns)
- Security context for user/group/fsGroup
- Resource requests/limits (memory: 512Mi-2Gi, cpu: 200m-2000m)

**Prometheus Stack (/Users/bret/git/homelab/k8s/prometheus-stack-app.yaml)**
- ArgoCD Application pattern for Helm chart deployment
- Reference for deploying Tailscale operator via ArgoCD
- Multi-source pattern (Helm chart + values repository) if needed
- Helm chart versioning approach (targetRevision)
- Namespace and server configuration pattern

**Vault Integration for Secrets**
- Follow existing pattern for retrieving secrets from Vault (seen in Terraform/Ansible workflows)
- Store Tailscale auth keys at secret/tailscale/auth-keys path in Vault
- Use Kubernetes ServiceAccount for Vault authentication if available
- Ensure proper Vault policies for Tailscale namespace/service to read auth keys

## Out of Scope
- Advanced NGINX features: connection pooling, sophisticated health checks, automatic failover
- Granular per-service ACL policies (starting permissive, tightening later is out of scope for initial migration)
- Tailscale SSH replacement for traditional SSH access
- Tailscale Serve for internal HTTPS termination
- Exit nodes for routing internet traffic through tailnet
- Service mesh integration (Istio/Linkerd)
- Advanced multi-cluster Tailscale capabilities
- Certificate rotation automation (Tailscale handles this automatically)
- Load balancing across multiple NGINX instances (single instance sufficient initially)
- NGINX Ingress Controller replacement (internal NGINX is separate from existing Ingress Controller)
- Migration of services not currently in NGINX Proxy Manager inventory
