# Spec Requirements: Tailscale Migration

## Initial Description

Migrate homelab infrastructure from Cloudflare DNS + NGINX Proxy Manager architecture to Tailscale-based zero-trust mesh networking while maintaining public access for two specific services (Kibana and CCHS Makerspace) via Tailscale Funnel.

## Complete Service Inventory from NGINX Proxy Manager

**18 Total Services Currently Proxied:**

| Service | Public Domain | Backend Target | Port | Public Access Required |
|---------|---------------|----------------|------|------------------------|
| Actual Budget | actual.bwortman.us | 192.168.10.250 | 5007 | No |
| ArgoCD | argocd.bwortman.us | kube.lb.thewortmans.org | 8443 | No |
| CCHS Makerspace | cchs.makerspace.hcbent.com | bdwlb.myddns.me | 7099 | **YES - Funnel** |
| CCHS Test | cchstest.makerspace.hcbent.com | bdwlb.myddns.me | 7098 | No |
| Cerebro (ES Admin) | cerebro.bwortman.us | bdwlb.myddns.me | 7008 | No |
| DF | df.bwortman.us | bdwlb.myddns.me | 7042 | No |
| DFK | dfk.bwortman.us | bdwlb.myddns.me | 7043 | No |
| Elasticsearch | elasticsearch.bwortman.us | bdwlb.myddns.me | 7005 | No |
| Kibana | kibana.bwortman.us | bdwlb.myddns.me | 7004 | **YES - Funnel** |
| Makerspace (alias) | makerspace.bwortman.us | bdwlb.myddns.me | 7099 | No (same as CCHS) |
| Mealie | mealie.bwortman.us | 192.168.10.250 | 9925 | No |
| Monitoring (ES Cluster) | monitoring.bwortman.us | bdwlb.myddns.me | 7009 | No |
| Paperless-ngx | paperless.bwortman.us | bdwlb.myddns.me | 7007 | No |
| Pi-hole | pihole.bwortman.us | bdwlb.myddns.me | 7012 | No |
| Plex | plex.bwortman.us | bdwlb.myddns.me | 7100 | No |
| qBittorrent | qbt.bwortman.us | kube.lb.thewortmans.org | 8090 | No |
| Radarr | radarr.bwortman.us | 192.168.10.250 | 7878 | No |
| Sonarr | sonarr.bwortman.us | 192.168.10.250 | 8989 | No |

**Backend Target Analysis:**

1. **Direct IP Services (192.168.10.250):**
   - Actual Budget (5007)
   - Mealie (9925)
   - Radarr (7878)
   - Sonarr (8989)

2. **Kubernetes Load Balancer Services (kube.lb.thewortmans.org):**
   - ArgoCD (8443)
   - qBittorrent (8090)

3. **Dynamic DNS Services (bdwlb.myddns.me):**
   - CCHS Makerspace & Test (7099, 7098)
   - Cerebro (7008)
   - DF/DFK (7042, 7043)
   - Elasticsearch (7005)
   - Kibana (7004)
   - Monitoring/ES Monitoring Cluster (7009)
   - Paperless-ngx (7007)
   - Pi-hole (7012)
   - Plex (7100)

**SSL/TLS Configuration:**
- All 18 services currently have Let's Encrypt SSL certificates via NGINX Proxy Manager
- All services use HTTPS termination at NGINX Proxy Manager
- Backend connections are HTTP (NGINX → service)

## Key Requirements from Initialization

1. Deploy Tailscale on Kubernetes cluster (km01, km02, km03)
2. Configure private access to all homelab services via Tailscale VPN mesh
3. Set up Tailscale Funnel for two public services:
   - kibana.bwortman.us
   - cchs.makerspace.hcbent.com
4. Deploy internal NGINX for clean URLs (replacing NGINX Proxy Manager)
5. Configure MagicDNS for service discovery
6. Enable on-demand Funnel for very infrequent service sharing (single user at a time)
7. Integrate with existing Vault for Tailscale auth keys
8. Decommission old NGINX Proxy Manager and Cloudflare configuration

## Requirements Discussion

### Architecture & Components

**Q1: Tailscale Kubernetes Deployment Pattern**
Should we use the Tailscale Kubernetes operator (recommended for service exposure) or DaemonSet approach (one pod per node)?

**Answer:** Use the Tailscale Kubernetes operator. This is the recommended approach for exposing Kubernetes services and provides better integration with K8s service discovery.

**Q2: Internal NGINX Configuration Scope**
For the internal NGINX deployment, should we implement a full-featured configuration with connection pooling, health checks, and automatic failover, or start with a minimal configuration for basic hostname routing and defer advanced features to a future phase?

**Answer:** Start with minimal configuration for basic hostname routing. Defer advanced features (connection pooling, health checks, failover) to a future phase. This keeps the initial migration focused and testable.

**Q3: MagicDNS Internal Domain**
What internal domain naming convention should we use for MagicDNS? Options include:
- *.home.lab
- *.tailscale.local
- *.homelab.internal

**Answer:** Use *.home.lab for internal DNS naming convention.

**Q4: Tailscale ACL Approach**
Should we implement granular per-service ACL policies from day one, or start with permissive "all users can access all services" ACLs and tighten gradually?

**Answer:** Start with permissive ACLs initially. This ensures nothing breaks during migration. We can tighten ACLs gradually after validating all services work correctly.

**Q5: Public Service Access Pattern**
For Kibana and CCHS Makerspace (the two services requiring public access), should they:
- A) Be accessible both via Tailscale mesh (for authenticated users) AND via Funnel (for public)?
- B) Only be accessible via Funnel (public only)?

**Answer:** Option A - Make them accessible both via Tailscale mesh (for private, authenticated access) AND via Funnel (for public access). This provides maximum flexibility.

**Q6: On-Demand Funnel Management**
How should we manage on-demand Funnel enabling/disabling? Should we create a script/tool, or is manual kubectl/CLI commands acceptable for this infrequent operation?

**Answer:** Create a script for on-demand Funnel management. Even though it's infrequent, having a script ensures consistency and reduces errors. The script should handle enable/disable operations cleanly.

**Q7: Rollback Window**
How long should we maintain the capability to roll back to the old NGINX Proxy Manager + Cloudflare architecture if issues arise?

**Answer:** Maintain rollback capability for 90 days post-migration. This provides adequate time to discover any edge cases or issues while not leaving legacy infrastructure in place indefinitely.

**Q8: Testing & Validation Timeline**
After migration completes, how long should we run both architectures in parallel (if at all) or test thoroughly before decommissioning the old setup?

**Answer:** Test thoroughly for 2 weeks before decommissioning. No parallel running - we'll do a phased migration where each service is fully cut over before moving to the next. The 2-week validation ensures all edge cases are covered.

**Q9: Service Migration Order**
Should we migrate services in a specific order? For example:
- Start with non-critical services (media apps)
- Move to critical services (home automation, finance)
- Finally migrate public services

**Answer:** Yes, use a phased approach:
- Phase 1: Tailscale foundation + Vault integration
- Phase 2: Internal NGINX + MagicDNS setup
- Phase 3: Media apps (Sonarr, Radarr, qBittorrent) - lowest risk
- Phase 4: Home apps (Actual Budget, etc.) - moderate risk
- Phase 5: CCHS Makerspace - higher visibility
- Phase 6: Elasticsearch Stack (4 services) - includes public-facing Kibana
- Phase 7: Everything else (3 services)
- Phase 8: Testing and validation (2 weeks)
- Phase 9: Decommission old infrastructure

**Q10: Monitoring Integration**
How should we integrate Tailscale monitoring with the existing Prometheus/Grafana stack?

**Answer:** Integrate Tailscale metrics into existing Prometheus stack:
- Tailscale connection status and metrics
- MagicDNS resolution health
- Funnel availability for public services
- Create dedicated Grafana dashboard for Tailscale visibility
- Set up alerts for node disconnections and Funnel unavailability
- Feed Tailscale audit logs into Elasticsearch/Kibana for access analysis

**Q11: Testing Strategy**
What testing approach should we use to validate the migration?

**Answer:** Comprehensive testing strategy:
- Test from multiple device types (laptop, phone, tablet)
- Test from multiple network locations (home WiFi, cellular, remote networks)
- Verify MagicDNS resolution works correctly
- Test all service functionality end-to-end
- Performance benchmarking vs. old architecture
- Public service access validation (without Tailscale connection)
- Funnel enable/disable workflow validation
- 2-week soak period before decommissioning old infrastructure

**Q12: Scope Exclusions**
What should we explicitly exclude from this migration?

**Answer:** No exclusions - all services should be migrated. The goal is complete transformation to Tailscale-based architecture.

### Existing Code Reuse

**Q13: Similar Existing Features**
Are there existing features in your codebase with similar patterns we should reference?

**Answer:** Found existing patterns in codebase:

**NGINX Ingress Controller:**
- Path: `/Users/bret/git/homelab/k8s/basement/nginx-ingress.yaml`
- Patterns to reuse:
  - ConfigMap-based configuration approach
  - ServiceAccount + ClusterRole + ClusterRoleBinding RBAC pattern
  - Deployment with health probes (liveness/readiness)
  - NodePort service type
  - Resource requests/limits definition
  - Using ingress-nginx controller v1.10.0

**Vault Deployment:**
- Path: `/Users/bret/git/homelab/k8s/basement/vault-deployment.yaml`
- Patterns to reuse:
  - StatefulSet for stateful services
  - ConfigMap for application configuration (vault.hcl pattern)
  - PersistentVolumeClaim with storageClassName
  - ServiceAccount with ClusterRole/ClusterRoleBinding
  - Ingress with nginx.ingress.kubernetes.io annotations
  - Resource requests/limits best practices
  - Security context configuration

**qBittorrent Service:**
- Path: `/Users/bret/git/homelab/k8s/media/qbittorrent-values.yaml`
- Patterns to reuse:
  - bjw-s app-template chart pattern (could be used for Tailscale)
  - NodePort service type (project standard)
  - Lifecycle hooks for post-start configuration
  - Health probes configuration
  - Persistent storage with multiple volumes (iSCSI + NFS)
  - Resource requests/limits
  - Security context for user/group/fsGroup

**Prometheus Stack:**
- Path: `/Users/bret/git/homelab/k8s/prometheus-stack-app.yaml`
- ArgoCD Application pattern for Helm chart deployment
- Multi-source pattern (Helm chart + values repository)

**NGINX Proxy Manager:**
- URL: http://truenas.lab.thewortmans.org:30020/nginx/proxy
- Current configuration to understand for migration

### Visual Assets Request

**Q14: Design Mockups**
Do you have any design mockups, wireframes, or screenshots that could help guide the development?

**Answer:** No visual assets provided.

## Visual Assets

### Files Provided:
No visual files found in `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/planning/visuals/`

### Visual Insights:
Not applicable - no visual assets provided.

## Requirements Summary

### PHASE 0 - CRITICAL PRECONDITION (BLOCKER)

**BLOCKER: Verify/Deploy Prometheus/Grafana Stack**

**CRITICAL CORRECTION:** monitoring.bwortman.us (bdwlb.myddns.me:7009) is NOT Prometheus/Grafana. It is part of the Elasticsearch monitoring cluster (a separate Elasticsearch instance used to monitor the main Elasticsearch cluster).

Before ANY other work begins, we must verify that the Prometheus/Grafana monitoring stack is deployed and functioning correctly. This is a hard dependency because:
- Tailscale monitoring metrics will feed into Prometheus
- Grafana dashboards will provide visibility into Tailscale mesh health
- Without working monitoring, we have no visibility into migration success/failure

**Phase 0 Tasks:**
1. Check if prometheus-stack ArgoCD application is deployed to cluster
   - Reference: `/Users/bret/git/homelab/k8s/prometheus-stack-app.yaml`
   - Verify the ArgoCD app exists and is synced
2. If NOT deployed, apply prometheus-stack-app.yaml to ArgoCD
3. Verify Prometheus is accessible and collecting metrics
4. Verify Grafana is accessible and dashboards are working
5. Confirm monitoring stack is ready to accept Tailscale metrics
6. Only after Phase 0 is complete can we proceed to Phase 1

**Status:** HARD BLOCKER - DO NOT PROCEED WITH TAILSCALE DEPLOYMENT UNTIL MONITORING IS OPERATIONAL

### Functional Requirements

#### Core Tailscale Infrastructure
- Deploy Tailscale Kubernetes operator across 3-node cluster (km01, km02, km03)
- Retrieve Tailscale auth keys from HashiCorp Vault (secret/tailscale/auth-keys)
- Configure MagicDNS with *.home.lab internal domain
- Implement permissive ACL policies initially (tighten post-migration)
- Deploy as NodePort service (project standard)

#### Internal NGINX Proxy Configuration

**Purpose:** Replace NGINX Proxy Manager with lightweight internal NGINX for *.home.lab routing

**Required Upstream Configurations:**

```nginx
# Media Services (Direct IP: 192.168.10.250)
upstream actual {
    server 192.168.10.250:5007;
}

upstream mealie {
    server 192.168.10.250:9925;
}

upstream radarr {
    server 192.168.10.250:7878;
}

upstream sonarr {
    server 192.168.10.250:8989;
}

# Kubernetes Services (kube.lb.thewortmans.org)
upstream argocd {
    server kube.lb.thewortmans.org:8443;
}

upstream qbittorrent {
    server kube.lb.thewortmans.org:8090;
}

# Dynamic DNS Services (bdwlb.myddns.me)
upstream cchs-makerspace {
    server bdwlb.myddns.me:7099;
}

upstream cchs-test {
    server bdwlb.myddns.me:7098;
}

upstream cerebro {
    server bdwlb.myddns.me:7008;
}

upstream df {
    server bdwlb.myddns.me:7042;
}

upstream dfk {
    server bdwlb.myddns.me:7043;
}

upstream elasticsearch {
    server bdwlb.myddns.me:7005;
}

upstream kibana {
    server bdwlb.myddns.me:7004;
}

upstream monitoring {
    server bdwlb.myddns.me:7009;
}

upstream paperless {
    server bdwlb.myddns.me:7007;
}

upstream pihole {
    server bdwlb.myddns.me:7012;
}

upstream plex {
    server bdwlb.myddns.me:7100;
}
```

**Server Block Configuration (*.home.lab):**

Each service will have a server block like:
```nginx
server {
    listen 80;
    server_name actual.home.lab;

    location / {
        proxy_pass http://actual;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Deferred Features (Future Phase):**
- Connection pooling (keepalive)
- Health checks (health_check directive)
- Automatic failover
- Advanced load balancing
- SSL/TLS termination (not needed in Tailscale mesh)

#### Service Discovery & DNS
- Configure MagicDNS for automatic resolution of *.home.lab
- Kubernetes nodes accessible via Tailscale hostnames
- Clean URL access: service.home.lab instead of IP:port
- DNS resolution order: Tailscale MagicDNS for internal, external DNS for internet

#### SSL/TLS Migration Strategy

**Current State (NGINX Proxy Manager):**
- All 18 services have Let's Encrypt SSL certificates
- SSL termination at NGINX Proxy Manager
- Backend connections are HTTP

**New State (Tailscale):**

1. **Private Services (16 services):**
   - NO SSL certificates needed
   - Traffic encrypted end-to-end via Tailscale mesh (WireGuard)
   - NGINX serves HTTP only (encryption handled by Tailscale)
   - *.home.lab domains accessed over encrypted tunnel

2. **Public Services via Funnel (2 services):**
   - kibana.bwortman.us
   - cchs.makerspace.hcbent.com
   - Tailscale Funnel automatically provides SSL/TLS
   - Uses Tailscale-managed certificates (*.ts.net domains)
   - Public DNS points to Tailscale Funnel endpoint

**SSL Certificate Cleanup:**
- Let's Encrypt certificates will be decommissioned with NGINX Proxy Manager
- No certificate renewal needed post-migration
- Simplified certificate management (Tailscale handles public endpoints)

#### DNS Cutover Plan for Public Services

**Phase 1: Preparation**
1. Set up Tailscale Funnel for kibana and cchs.makerspace
2. Obtain Funnel URLs (e.g., kibana-homelab.tailnet-abc123.ts.net)
3. Test Funnel endpoints thoroughly

**Phase 2: DNS Update**
1. Lower TTL on current DNS records to 300 seconds (5 minutes)
2. Wait 24 hours for TTL propagation
3. Update DNS records:
   - **kibana.bwortman.us** → CNAME to Tailscale Funnel endpoint
   - **cchs.makerspace.hcbent.com** → CNAME to Tailscale Funnel endpoint
4. Verify DNS propagation

**Phase 3: Validation**
1. Test public access from non-Tailscale networks
2. Verify SSL certificates working (Tailscale-provided)
3. Check all functionality end-to-end
4. Monitor for 2 weeks

**Phase 4: Cloudflare Cleanup**
1. Remove Cloudflare proxy (orange cloud) if enabled
2. Document final DNS configuration
3. Archive old DNS records

**DNS Records to Maintain:**
- kibana.bwortman.us (CNAME to Funnel)
- cchs.makerspace.hcbent.com (CNAME to Funnel)

**DNS Records to Deprecate:**
- All other *.bwortman.us subdomains (16 services moving to private-only access)

#### Private Service Migration (Phased)

**Phase 3: Media Services**
- sonarr.bwortman.us → sonarr.home.lab (192.168.10.250:8989)
- radarr.bwortman.us → radarr.home.lab (192.168.10.250:7878)
- qbt.bwortman.us → qbittorrent.home.lab (kube.lb.thewortmans.org:8090)

**Phase 4: Home Apps**
- actual.bwortman.us → actual.home.lab (192.168.10.250:5007)
- mealie.bwortman.us → mealie.home.lab (192.168.10.250:9925)
- paperless.bwortman.us → paperless.home.lab (bdwlb.myddns.me:7007)
- pihole.bwortman.us → pihole.home.lab (bdwlb.myddns.me:7012)

**Phase 5: CCHS Makerspace**
- cchs.makerspace.hcbent.com → PUBLIC via Funnel + makerspace.home.lab (bdwlb.myddns.me:7099)
- cchstest.makerspace.hcbent.com → cchstest.home.lab (bdwlb.myddns.me:7098)
- makerspace.bwortman.us → makerspace.home.lab (same backend as cchs)

**Phase 6: Elasticsearch Stack (4 services)**
- kibana.bwortman.us → PUBLIC via Funnel + kibana.home.lab (bdwlb.myddns.me:7004)
- elasticsearch.bwortman.us → elasticsearch.home.lab (bdwlb.myddns.me:7005)
- cerebro.bwortman.us → cerebro.home.lab (bdwlb.myddns.me:7008)
- monitoring.bwortman.us → monitoring.home.lab (bdwlb.myddns.me:7009) - ES monitoring cluster

**Phase 7: Everything Else (3 services)**
- argocd.bwortman.us → argocd.home.lab (kube.lb.thewortmans.org:8443)
- plex.bwortman.us → plex.home.lab (bdwlb.myddns.me:7100)
- df.bwortman.us → df.home.lab (bdwlb.myddns.me:7042)
- dfk.bwortman.us → dfk.home.lab (bdwlb.myddns.me:7043)

All private services accessible only via Tailscale mesh.

#### Public Service Exposure
- Configure permanent Tailscale Funnel for kibana.bwortman.us
- Configure permanent Tailscale Funnel for cchs.makerspace.hcbent.com
- Both services accessible via Funnel (public) AND Tailscale mesh (private)
- Automatic HTTPS certificate management via Tailscale

#### On-Demand Service Sharing
- Script-based Funnel enable/disable functionality
- Support temporary public access for any service
- Quick disable procedure after sharing period
- Single-user temporary sharing use case

#### Monitoring & Observability
- Integrate Tailscale metrics into existing Prometheus stack
- Create Grafana dashboard for Tailscale mesh health
- Monitor: node connectivity, MagicDNS resolution, Funnel availability
- Configure alerts for disconnections and Funnel unavailability
- Feed Tailscale audit logs into Elasticsearch/Kibana
- Access pattern analysis and visibility
- Monitor ALL services via *.home.lab, including the ES monitoring cluster

#### Testing & Validation
- End-to-end testing from multiple devices (laptop, phone, tablet)
- Multi-network testing (home WiFi, cellular, remote)
- MagicDNS resolution validation
- Service functionality verification for all 18 services
- Performance benchmarking vs. old architecture
- Public service access validation (kibana, cchs.makerspace)
- 2-week soak period before decommissioning

#### Infrastructure Cleanup
- Decommission NGINX Proxy Manager after 2-week validation
- Remove all port forwarding rules
- Update/remove Cloudflare DNS records (16 private services)
- Update DNS for 2 public services (point to Funnel)
- Archive old configuration for 90-day rollback window

### Reusability Opportunities

**Components from Existing Codebase:**
- NGINX ingress controller deployment pattern (ConfigMap, ServiceAccount, RBAC)
- Vault StatefulSet pattern for stateful Tailscale components if needed
- bjw-s app-template chart pattern for Helm-based Tailscale deployment
- NodePort service type standard across all new services
- Health probe configuration patterns
- Resource request/limit standards
- Security context patterns
- Lifecycle hooks for post-start configuration
- ArgoCD Application pattern for GitOps management

**Backend Patterns to Investigate:**
- Vault integration for secret retrieval (existing pattern in Terraform/Ansible)
- Prometheus metrics export (existing Prometheus stack)
- Elasticsearch log shipping (existing Fleet + Elastic Agent)

**Similar Features to Model After:**
- NGINX Ingress Controller for NGINX deployment approach
- Vault deployment for ConfigMap-based configuration
- qBittorrent for bjw-s chart pattern and service configuration
- Prometheus stack for ArgoCD Application deployment

### Scope Boundaries

**In Scope:**
- Complete migration of all 18 homelab services to Tailscale mesh
- Tailscale Kubernetes operator deployment
- Internal NGINX proxy for clean URLs (18 upstream configurations)
- MagicDNS configuration for *.home.lab (18 service DNS entries)
- Permanent Funnel for kibana.bwortman.us and cchs.makerspace.hcbent.com
- DNS cutover for 2 public services
- DNS deprecation for 16 private services
- SSL/TLS migration strategy (certificate decommissioning)
- On-demand Funnel script for temporary sharing
- Vault integration for Tailscale auth keys
- Monitoring integration (Prometheus/Grafana + Elasticsearch/Kibana)
- Comprehensive testing and validation (all 18 services)
- 2-week soak period
- NGINX Proxy Manager decommission
- Port forwarding removal
- Cloudflare DNS cleanup
- Complete documentation and runbooks

**Out of Scope (Deferred to Future Phase):**
- Advanced NGINX features (connection pooling, sophisticated health checks, automatic failover)
- Granular per-service ACL policies (starting permissive, tightening later)
- Tailscale SSH replacement for traditional SSH
- Tailscale Serve for internal HTTPS
- Exit nodes for routing internet traffic
- Service mesh (Istio/Linkerd)
- Advanced multi-cluster capabilities

**Critical Blocker:**
- Phase 0: Verify Prometheus/Grafana monitoring stack is operational (MUST be completed before any other work)

### Technical Considerations

**Integration Points:**
- HashiCorp Vault for Tailscale auth key storage and retrieval
- Kubernetes cluster (K3s) with 3 control plane nodes
- Existing Prometheus/Grafana monitoring stack (must be verified/deployed first - Phase 0)
- Existing Elasticsearch/Kibana logging infrastructure at kibana.bwortman.us
- Existing Elasticsearch monitoring cluster at monitoring.bwortman.us
- ArgoCD for GitOps management
- Democratic CSI for storage provisioning
- NodePort service type (project standard)

**Backend Target Types:**
1. Direct IP: 192.168.10.250 (4 services)
2. Kubernetes LB: kube.lb.thewortmans.org (2 services)
3. Dynamic DNS: bdwlb.myddns.me (12 services)

**Technology Stack:**
- Tailscale Kubernetes operator (not DaemonSet)
- Standard NGINX (not NGINX Proxy Manager)
- Helm for package management
- ArgoCD for continuous deployment
- Vault for secret management
- Prometheus/Grafana for metrics
- Elasticsearch/Kibana for logs and audit trails
- MagicDNS for internal service discovery

**Existing System Constraints:**
- 3-node Kubernetes cluster (km01, km02, km03)
- NFS share called "tank" for storage
- NodePort service type preference
- Vault-based secret management requirement
- GitOps workflow with ArgoCD
- Infrastructure-as-code approach (Terraform, Ansible, Kubernetes manifests)

**Similar Code Patterns to Follow:**
- NGINX Ingress Controller: ConfigMap configuration, RBAC, health probes, NodePort
- Vault deployment: StatefulSet, ConfigMap, ServiceAccount, resource limits
- qBittorrent: bjw-s chart, lifecycle hooks, security context, persistent storage
- Prometheus stack: ArgoCD Application for Helm charts

**Migration Strategy:**
- Phased approach with incremental validation
- No parallel running - full cutover per service
- 2-week validation period after all services migrated
- 90-day rollback window with documented procedures
- Zero downtime for critical services during migration
- Each phase validates before moving to next

**Performance Expectations:**
- Performance benchmarking against old architecture
- Validate streaming quality (Plex, media services)
- Measure file transfer speeds
- Ensure no degradation from current state
- Monitor for bottlenecks during soak period

**Security Requirements:**
- Zero port forwarding on external firewall post-migration
- All private services (16) accessible only through encrypted Tailscale mesh
- Public exposure limited to 2 Funnel endpoints
- Complete audit trail via Tailscale logging → Elasticsearch
- Permissive ACLs initially, tighten gradually post-validation
- Infrastructure-as-code for all networking changes (version-controlled, auditable)

### Deliverables

**Scripts:**
- Funnel enable/disable script for on-demand service sharing
- Tailscale ACL update/validation scripts

**Documentation:**
- User access guide (connecting to Tailscale, accessing services)
- Service catalog with new URLs:
  - 16 private services: *.home.lab URLs
  - 2 public services: *.bwortman.us and *.hcbent.com via Funnel
- Operational runbooks (adding services, Funnel management, troubleshooting)
- Rollback procedures (step-by-step, maintained for 90 days)
- Network architecture diagrams
- Infrastructure-as-code documentation
- NGINX upstream configuration documentation (18 services)
- DNS cutover procedures

**Monitoring:**
- Grafana dashboard for Tailscale mesh health
- Prometheus alerts for connectivity and availability
- Kibana dashboards for access patterns and audit logs
- Service availability monitoring (all 18 services)

**Infrastructure:**
- All Tailscale configurations in version-controlled git repository
- ArgoCD Application for Tailscale deployment
- Kubernetes manifests for internal NGINX (18 upstream configs)
- Vault policies and secret structure
- Clean, documented ACL policies

## Migration Phases Detail

### Phase 0: PROMETHEUS/GRAFANA VERIFICATION (BLOCKER)
**Status:** MUST BE COMPLETED BEFORE ANY OTHER WORK

**CRITICAL CORRECTION:** monitoring.bwortman.us (bdwlb.myddns.me:7009) is NOT Prometheus/Grafana - it is part of the Elasticsearch monitoring cluster (a separate Elasticsearch instance used to monitor the main Elasticsearch cluster).

**Tasks:**
1. Check if prometheus-stack ArgoCD app is deployed to cluster
   - Reference: `/Users/bret/git/homelab/k8s/prometheus-stack-app.yaml`
   - Command: `kubectl get application prometheus-stack -n argocd`
2. If not deployed, apply prometheus-stack-app.yaml to ArgoCD
   - Command: `kubectl apply -f /Users/bret/git/homelab/k8s/prometheus-stack-app.yaml`
3. Verify Prometheus is accessible and collecting metrics
4. Verify Grafana is accessible and dashboards are working
5. Confirm Grafana dashboards are functional
6. Validate monitoring pipeline is ready to accept Tailscale metrics

**Note:** This is a HARD BLOCKER - do not proceed with Tailscale deployment until monitoring is operational.

**Exit Criteria:** Prometheus scraping metrics, Grafana accessible and functional, dashboards working

### Phase 1: Foundation & Vault Integration
**Dependencies:** Phase 0 complete

**Tasks:**
1. Tailscale account setup and organization configuration
2. Generate Tailscale auth keys (reusable, tagged for K8s)
3. Store auth keys in Vault at secret/tailscale/auth-keys
4. Deploy Tailscale Kubernetes operator to cluster
5. Verify all 3 nodes (km01, km02, km03) appear in tailnet
6. Configure MagicDNS globally
7. Test DNS resolution from Tailscale-connected devices

**Exit Criteria:** All nodes in tailnet with MagicDNS working

### Phase 2: Internal NGINX & Service Discovery
**Dependencies:** Phase 1 complete

**Tasks:**
1. Deploy standard NGINX to Kubernetes as NodePort
2. Create ConfigMap with 18 upstream definitions:
   - 4 direct IP upstreams (192.168.10.250)
   - 2 Kubernetes LB upstreams (kube.lb.thewortmans.org)
   - 12 dynamic DNS upstreams (bdwlb.myddns.me)
3. Configure 18 server blocks for *.home.lab domains
4. Configure *.home.lab internal domain in MagicDNS
5. Test hostname-based routing for all services
6. Verify MagicDNS resolution to NGINX

**Exit Criteria:** Clean URL access working (service.home.lab) for test services

### Phase 3: Media Services Migration
**Dependencies:** Phase 2 complete
**Risk:** Low (non-critical services)

**Services (4 total):**
- sonarr.bwortman.us → sonarr.home.lab (192.168.10.250:8989)
- radarr.bwortman.us → radarr.home.lab (192.168.10.250:7878)
- qbt.bwortman.us → qbittorrent.home.lab (kube.lb.thewortmans.org:8090)
- plex.bwortman.us → plex.home.lab (bdwlb.myddns.me:7100)

**Tasks:**
1. Update NGINX routing for media services
2. Test access via *.home.lab URLs from Tailscale-connected devices
3. Verify functionality end-to-end:
   - Sonarr: series management, downloads
   - Radarr: movie management, downloads
   - qBittorrent: torrent operations, WebUI
   - Plex: media streaming, library access
4. Document new access patterns
5. Update bookmarks/shortcuts for users

**Exit Criteria:** All 4 media services accessible and functional via Tailscale

### Phase 4: Home Apps Migration
**Dependencies:** Phase 3 complete
**Risk:** Moderate (includes financial app)

**Services (4 total):**
- actual.bwortman.us → actual.home.lab (192.168.10.250:5007)
- mealie.bwortman.us → mealie.home.lab (192.168.10.250:9925)
- paperless.bwortman.us → paperless.home.lab (bdwlb.myddns.me:7007)
- pihole.bwortman.us → pihole.home.lab (bdwlb.myddns.me:7012)

**Tasks:**
1. Update NGINX routing for home apps
2. Test mobile app connectivity if applicable
3. Verify all web interfaces functional:
   - Actual Budget: budget management, sync
   - Mealie: recipe access, meal planning
   - Paperless-ngx: document search, upload
   - Pi-hole: DNS blocking, admin interface
4. Test file upload/download functionality
5. Document new access patterns

**Exit Criteria:** All 4 home apps accessible and functional

### Phase 5: CCHS Makerspace Migration
**Dependencies:** Phase 4 complete
**Risk:** Moderate (public-facing)

**Services (3 total):**
- cchs.makerspace.hcbent.com → PUBLIC via Funnel + makerspace.home.lab (bdwlb.myddns.me:7099)
- cchstest.makerspace.hcbent.com → cchstest.home.lab (bdwlb.myddns.me:7098)
- makerspace.bwortman.us → makerspace.home.lab (same backend as cchs)

**Tasks:**
1. Configure permanent Tailscale Funnel for cchs.makerspace.hcbent.com
2. Update DNS records (CNAME to Funnel endpoint)
3. Configure private access via makerspace.home.lab
4. Test public access without Tailscale (Funnel)
5. Test private access via Tailscale mesh
6. Verify TLS certificates (Tailscale-provided)
7. Validate all application functionality

**Exit Criteria:** CCHS Makerspace accessible both publicly (Funnel) and privately (Tailscale)

### Phase 6: Elasticsearch Stack Migration (4 services)
**Dependencies:** Phase 5 complete
**Risk:** Moderate (public-facing, logging infrastructure)

**Services (4 total):**
- kibana.bwortman.us → PUBLIC via Funnel + kibana.home.lab (bdwlb.myddns.me:7004)
- elasticsearch.bwortman.us → elasticsearch.home.lab (bdwlb.myddns.me:7005)
- cerebro.bwortman.us → cerebro.home.lab (bdwlb.myddns.me:7008)
- monitoring.bwortman.us → monitoring.home.lab (bdwlb.myddns.me:7009) - ES monitoring cluster

**Description:** This phase includes the main Elasticsearch service, Kibana (public), Cerebro (ES admin tool), and the Elasticsearch monitoring cluster (a separate Elasticsearch instance used to monitor the main cluster).

**Tasks:**
1. Configure permanent Tailscale Funnel for kibana.bwortman.us
2. Update DNS records (CNAME to Funnel endpoint)
3. Configure private access for all four services
4. Test public access to Kibana without Tailscale (Funnel)
5. Test private access via Tailscale mesh
6. Verify TLS certificates (Tailscale-provided)
7. Validate Elasticsearch backend connectivity
8. Test Cerebro admin functionality
9. Verify ES monitoring cluster functionality

**Exit Criteria:** Kibana accessible both publicly (Funnel) and privately (Tailscale), Elasticsearch/Cerebro/Monitoring private-only

### Phase 7: Remaining Services Migration (3 services)
**Dependencies:** Phase 6 complete
**Risk:** Low to moderate

**Services (3 total):**
- argocd.bwortman.us → argocd.home.lab (kube.lb.thewortmans.org:8443)
- df.bwortman.us → df.home.lab (bdwlb.myddns.me:7042)
- dfk.bwortman.us → dfk.home.lab (bdwlb.myddns.me:7043)

**Tasks:**
1. Migrate all remaining services to *.home.lab
2. Update NGINX routing configurations
3. Test all services individually:
   - ArgoCD: application management, sync operations
   - DF/DFK: whatever these services do
4. Verify Tailscale metrics appearing in Grafana
5. Document access patterns

**Exit Criteria:** All 18 services migrated and accessible via Tailscale

### Phase 8: Testing & Validation (2 weeks)
**Dependencies:** Phase 7 complete

**Tasks:**
1. Comprehensive end-to-end testing from all device types:
   - Laptop (macOS/Windows/Linux)
   - Phone (iOS/Android)
   - Tablet
2. Multi-network location testing:
   - Home WiFi
   - Cellular (4G/5G)
   - Remote networks (coffee shop, work)
3. Service-specific validation (all 18 services):
   - Verify each service's core functionality
   - Test data persistence
   - Validate integrations between services
4. Performance benchmarking vs. old architecture:
   - Page load times
   - Media streaming quality (Plex)
   - File transfer speeds (Paperless, media apps)
   - API response times
5. Public service validation:
   - Kibana public access (no Tailscale)
   - CCHS Makerspace public access (no Tailscale)
   - SSL certificate validation
6. Security validation:
   - Confirm no port forwarding active
   - Verify private services inaccessible without Tailscale
   - Test ACL policies
   - Review audit logs in Elasticsearch
7. Funnel on-demand workflow testing:
   - Enable Funnel for test service
   - Verify public access
   - Disable Funnel
   - Verify public access removed
8. Monitoring dashboard validation:
   - Tailscale mesh health visible in Grafana
   - Alerts configured and functional
   - Metrics populating correctly
9. Document any issues found and resolve

**Exit Criteria:** 2 weeks of stable operation, all tests passed, no critical issues

### Phase 9: Infrastructure Cleanup
**Dependencies:** Phase 8 complete (2-week soak successful)

**Tasks:**
1. Export NGINX Proxy Manager configuration for reference
2. Shut down and remove NGINX Proxy Manager container/VM
3. Remove port forwarding rules from router/firewall
4. DNS updates in Cloudflare:
   - Remove DNS records for 16 private services (*.bwortman.us)
   - Keep 2 public service records (kibana, cchs.makerspace) pointing to Funnel
5. Verify no external ports open (nmap scan)
6. Archive old configuration files:
   - NGINX Proxy Manager exports
   - Old DNS records
   - Port forwarding rules
   - Cloudflare configurations
7. Maintain archive for 90-day rollback window
8. Update infrastructure documentation:
   - Network architecture diagrams
   - Service inventory
   - Access procedures
   - Troubleshooting guides
9. Create rollback procedures document (valid for 90 days)

**Exit Criteria:** Old infrastructure decommissioned, rollback docs maintained, zero port forwarding active

### Future Phase: NGINX Enhancements (Deferred)
**Dependencies:** Phase 9 complete, system stable

**Tasks:**
1. Implement connection pooling (keepalive) for all 18 upstreams
2. Add sophisticated health checks (health_check directive)
3. Configure automatic failover for critical services
4. Optimize performance tuning
5. Advanced upstream configuration (backup servers, weights)
6. Implement request/connection limiting
7. Add caching where appropriate

**Exit Criteria:** Enhanced NGINX features operational, performance improved

## Success Metrics

**Security:**
- Zero port forwarding rules on external firewall
- All 16 private services accessible only via encrypted Tailscale mesh
- Complete audit trail in Elasticsearch/Kibana for all 18 services
- Public exposure limited to 2 Funnel endpoints (kibana, cchs.makerspace)
- No SSL certificate management burden (Tailscale handles public endpoints)

**Usability:**
- Clean URLs (*.home.lab) working for all 18 services
- Single configuration point (Tailscale ACLs) for access control
- Seamless roaming between networks (WiFi, cellular, remote)
- Temporary sharing accomplished in under 5 minutes via script
- No IP:port combinations to remember

**Reliability:**
- Zero downtime during migration (phased cutover)
- Performance equal to or better than old architecture
- Monitoring visibility into mesh health (Grafana dashboard)
- 2-week stable operation before decommission
- Service availability monitoring for all 18 services

**Operations:**
- All configurations version-controlled (Git)
- Complete documentation and runbooks
- 90-day rollback capability maintained
- Infrastructure-as-code for all changes
- Simplified certificate management (no Let's Encrypt renewals)
- Single NGINX configuration file with 18 upstreams

**Service Coverage:**
- 18 services successfully migrated
- 2 public services via Funnel with dual access (public + private)
- 16 private services via Tailscale mesh only
- All services tested and validated
- Zero services left on old architecture
