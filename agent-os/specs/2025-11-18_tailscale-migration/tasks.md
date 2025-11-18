# Task Breakdown: Tailscale Migration

## Overview
**Goal:** Migrate 18 homelab services from Cloudflare DNS + NGINX Proxy Manager to Tailscale mesh networking

**Total Services:** 18 (2 public via Funnel, 16 private-only)
**Implementation Phases:** 9
**Total Task Groups:** 11
**Validation Period:** 2 weeks
**Rollback Window:** 90 days

## Task List

### PHASE 0: PROMETHEUS/GRAFANA VERIFICATION (CRITICAL BLOCKER)

#### Task Group 0: Monitoring Stack Verification
**Dependencies:** None
**Status:** COMPLETED

**IMPORTANT:** monitoring.bwortman.us is NOT Prometheus/Grafana. It is part of the Elasticsearch monitoring cluster (a separate Elasticsearch instance used to monitor the main Elasticsearch cluster).

- [x] 0.0 Verify/Deploy Prometheus/Grafana monitoring stack
  - [x] 0.1 Check ArgoCD application status
    - Command: `kubectl get application prometheus-stack -n argocd`
    - Reference file: `/Users/bret/git/homelab/k8s/prometheus-stack-app.yaml`
    - Verify application exists and is synced
    - RESULT: Application was not deployed initially
  - [x] 0.2 Deploy prometheus-stack if not present
    - Created prometheus namespace
    - Applied `/Users/bret/git/homelab/k8s/prometheus-stack-app.yaml`
    - Fixed CRD annotation size issue by adding ServerSideApply=true
    - Restarted operator to trigger reconciliation
    - All pods deployed successfully
  - [x] 0.3 Verify Prometheus accessibility
    - Prometheus service running at prometheus-stack-kube-prom-prometheus:9090
    - Prometheus API accessible and functional
    - Confirmed scraping is working: 47 active targets
  - [x] 0.4 Verify Grafana accessibility
    - Grafana service running at prometheus-stack-grafana:80
    - Grafana health endpoint confirmed: version 12.1.0
    - Service is accessible and healthy
  - [x] 0.5 Validate monitoring pipeline readiness
    - Prometheus is running and collecting metrics from 47 targets
    - Alertmanager is running (2/2 pods ready)
    - All monitoring CRDs installed successfully
    - Ready to accept new scrape targets for Tailscale metrics
  - [x] 0.6 Document current monitoring stack status
    - Prometheus version: v3.5.0
    - Grafana version: 12.1.0
    - Application status: Synced and Healthy
    - Running pods: 11/12 running (1 completed job)
    - 32 dashboard configmaps deployed
    - Service endpoints: prometheus:9090, grafana:80, alertmanager:9093
    - Configuration changes made: Added ServerSideApply=true to avoid CRD annotation size limits

**Acceptance Criteria:**
- [x] Prometheus is running and collecting metrics (47 active targets)
- [x] Grafana is accessible with functional dashboards (version 12.1.0)
- [x] Monitoring stack ready to accept Tailscale metrics
- [x] BLOCKER STATUS CLEARED

---

### PHASE 1: TAILSCALE FOUNDATION & VAULT INTEGRATION

#### Task Group 1: Tailscale Account Setup
**Dependencies:** Task Group 0 complete (✓ COMPLETED)
**Status:** READY FOR USER EXECUTION

- [ ] 1.0 Configure Tailscale account and generate auth keys
  - [ ] 1.1 Create/verify Tailscale account organization
    - Access Tailscale admin console: https://login.tailscale.com/admin
    - Verify organization settings
    - Document organization name and tailnet name
    - Instructions: See `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-1-instructions.md`
  - [ ] 1.2 Generate reusable, tagged auth keys
    - Create auth key with tags: kubernetes, homelab
    - Set auth key as reusable
    - Set appropriate expiration (1 year+)
    - Copy auth key to secure temporary location
    - Instructions: See Task Group 1 instructions document
  - [ ] 1.3 Store auth keys in Vault
    - Path: `secret/tailscale/auth-keys`
    - Store auth key value using provided script
    - Verify Vault policies allow Kubernetes access
    - Test retrieval from Vault
    - Script: `/Users/bret/git/homelab/tailscale/scripts/store-auth-key.sh`
  - [ ] 1.4 Configure Tailscale ACL policy (permissive initial state)
    - Apply permissive "all users can access all services" policy
    - Policy file: `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json`
    - Save ACL configuration to git repository (already done)
    - Apply ACL in Tailscale admin console: https://login.tailscale.com/admin/acls

**Implementation Files Created:**
- [x] `/Users/bret/git/homelab/agent-os/specs/2025-11-18_tailscale-migration/implementation/task-group-1-instructions.md` - Detailed step-by-step instructions
- [x] `/Users/bret/git/homelab/tailscale/scripts/store-auth-key.sh` - Vault storage script with verification
- [x] `/Users/bret/git/homelab/tailscale/acl-policy-permissive.json` - Permissive ACL policy for initial deployment
- [x] `/Users/bret/git/homelab/tailscale/organization-info-template.txt` - Template for documenting org details
- [x] `/Users/bret/git/homelab/tailscale/README.md` - Comprehensive documentation
- [x] `/Users/bret/git/homelab/tailscale/QUICKSTART.md` - Quick reference guide
- [x] `/Users/bret/git/homelab/tailscale/.gitignore` - Exclude sensitive files from git

**Acceptance Criteria:**
- [ ] Tailscale organization configured and documented
- [ ] Reusable auth keys generated with correct tags and stored in Vault
- [ ] Vault policy `tailscale-k8s` created and verified
- [ ] Permissive ACL policy applied in Tailscale admin console
- [ ] All configuration files committed to git (except sensitive data)

**User Action Required:**
Follow the instructions in the files listed above to complete the manual steps:
1. Access Tailscale admin console and document organization details
2. Generate auth key with appropriate tags and settings
3. Run the Vault storage script to store the auth key
4. Apply the ACL policy in Tailscale admin console

---

### PHASE 1 (continued): TAILSCALE FOUNDATION & VAULT INTEGRATION

#### Task Group 2: Tailscale Kubernetes Operator Deployment
**Dependencies:** Task Group 1 complete
**Status:** PENDING

- [ ] 2.0 Deploy Tailscale Kubernetes operator
  - [ ] 2.1 Create Tailscale namespace and RBAC
    - Create namespace: tailscale
    - Create ServiceAccount for operator
    - Create ClusterRole with required permissions
    - Create ClusterRoleBinding
    - Follow pattern from nginx-ingress.yaml
  - [ ] 2.2 Create ConfigMap for operator configuration
    - Vault address and path configuration
    - Operator settings (polling interval, log level)
    - Follow ConfigMap pattern from vault-deployment.yaml
  - [ ] 2.3 Deploy operator as Deployment
    - Use tailscale/k8s-operator image
    - Configure Vault integration for auth key retrieval
    - Set resource requests/limits
    - Configure liveness and readiness probes
    - Deploy as NodePort service
  - [ ] 2.4 Verify operator deployment
    - Check pod status: Running
    - Verify operator can read auth key from Vault
    - Check operator logs for successful initialization
  - [ ] 2.5 Verify nodes appear in tailnet
    - Check Tailscale admin console
    - Verify km01, km02, km03 appear with kubernetes tag
    - Test connectivity between nodes via Tailscale
  - [ ] 2.6 Document operator deployment
    - Kubernetes manifests committed to git
    - Deployment status recorded
    - Node hostnames in tailnet documented

**Acceptance Criteria:**
- Tailscale operator deployed and running
- All 3 Kubernetes nodes visible in tailnet
- Operator successfully retrieving auth keys from Vault
- Health probes passing

---

#### Task Group 3: MagicDNS Configuration
**Dependencies:** Task Group 2 complete
**Status:** PENDING

- [ ] 3.0 Configure MagicDNS for *.home.lab
  - [ ] 3.1 Enable MagicDNS globally in Tailscale console
    - Navigate to DNS settings in admin console
    - Enable MagicDNS feature
    - Set override local DNS: Yes
  - [ ] 3.2 Configure internal domain suffix
    - Set custom domain to: home.lab
    - Configure nameservers if needed
  - [ ] 3.3 Test DNS resolution from Tailscale-connected device
    - Install Tailscale on test device (laptop/phone)
    - Connect to tailnet
    - Test resolution of km01, km02, km03 by hostname
    - Verify tailnet domain resolution
  - [ ] 3.4 Document MagicDNS configuration
    - DNS settings saved to git
    - Resolution order documented
    - Test results recorded

**Acceptance Criteria:**
- MagicDNS enabled globally
- *.home.lab domain configured
- DNS resolution working from Tailscale clients
- Kubernetes nodes resolvable by hostname

---

### PHASE 2: INTERNAL NGINX & SERVICE DISCOVERY

#### Task Group 4: Internal NGINX Proxy Deployment
**Dependencies:** Task Group 3 complete
**Status:** PENDING

- [ ] 4.0 Deploy standard NGINX to Kubernetes
  - [ ] 4.1 Create NGINX ConfigMap with 18 upstream definitions
    - 4 direct IP upstreams (192.168.10.250:port)
    - 2 Kubernetes LB upstreams (kube.lb.thewortmans.org:port)
    - 12 dynamic DNS upstreams (bdwlb.myddns.me:port)
    - Follow ConfigMap pattern from nginx-ingress.yaml
  - [ ] 4.2 Configure 18 server blocks for *.home.lab
    - Create server block for each service
    - Configure proxy_pass to corresponding upstream
    - Set proxy headers (Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto)
    - HTTP only (no SSL - handled by Tailscale)
  - [ ] 4.3 Deploy NGINX as Deployment
    - Use official nginx:latest or nginx:stable image
    - Mount ConfigMap as nginx.conf
    - Set resource requests/limits
    - Configure health probes
  - [ ] 4.4 Create NodePort Service for NGINX
    - Expose port 80 via NodePort
    - Follow NodePort pattern from project standard
  - [ ] 4.5 Verify NGINX deployment
    - Check pod status: Running
    - Test direct access to NodePort
    - Verify nginx config syntax
    - Check nginx access/error logs
  - [ ] 4.6 Test service routing
    - Test at least 3 services via NodePort
    - Verify upstream connectivity
    - Check proxy headers are set correctly

**Acceptance Criteria:**
- NGINX deployed and running in Kubernetes
- All 18 upstream definitions configured
- All 18 server blocks configured
- NodePort service accessible
- Basic routing working to backend services

---

#### Task Group 5: Service DNS Integration
**Dependencies:** Task Group 4 complete
**Status:** PENDING

- [ ] 5.0 Integrate services with MagicDNS
  - [ ] 5.1 Configure NGINX hostname in MagicDNS
    - Determine NGINX Tailscale hostname
    - Ensure NGINX is accessible via Tailscale mesh
  - [ ] 5.2 Create DNS records for 18 services
    - Map each *.home.lab domain to NGINX endpoint
    - Verify MagicDNS resolves service names
  - [ ] 5.3 Test end-to-end access
    - From Tailscale-connected device
    - Access actual.home.lab, sonarr.home.lab, etc.
    - Verify services load correctly
  - [ ] 5.4 Document service URLs
    - Create service catalog with all *.home.lab URLs
    - Include backend target information
    - Commit to git

**Acceptance Criteria:**
- All 18 services accessible via *.home.lab URLs
- MagicDNS resolving correctly
- End-to-end connectivity verified
- Service catalog documented

---

### PHASE 3-7: SERVICE MIGRATION (Grouped by Category)

#### Task Group 6: Media Services Migration (Phase 3)
**Dependencies:** Task Group 5 complete
**Status:** PENDING
**Risk:** Low (non-critical services)

**Services:** sonarr, radarr, qbittorrent, plex

- [ ] 6.0 Migrate media services to Tailscale
  - [ ] 6.1 Update NGINX configuration for media services
  - [ ] 6.2 Test access via *.home.lab URLs
  - [ ] 6.3 Verify service functionality
    - Sonarr: series management, downloads
    - Radarr: movie management, downloads
    - qBittorrent: torrent operations, WebUI
    - Plex: media streaming, library access
  - [ ] 6.4 Update user bookmarks/shortcuts
  - [ ] 6.5 Document migration completion

**Acceptance Criteria:**
- All 4 media services accessible via Tailscale
- Service functionality verified end-to-end
- User access patterns updated

---

#### Task Group 7: Home Apps Migration (Phase 4)
**Dependencies:** Task Group 6 complete
**Status:** PENDING
**Risk:** Moderate (includes financial app)

**Services:** actual, mealie, paperless, pihole

- [ ] 7.0 Migrate home apps to Tailscale
  - [ ] 7.1 Update NGINX configuration for home apps
  - [ ] 7.2 Test mobile app connectivity if applicable
  - [ ] 7.3 Verify service functionality
    - Actual Budget: budget management, sync
    - Mealie: recipe access, meal planning
    - Paperless-ngx: document search, upload
    - Pi-hole: DNS blocking, admin interface
  - [ ] 7.4 Test file upload/download functionality
  - [ ] 7.5 Document migration completion

**Acceptance Criteria:**
- All 4 home apps accessible via Tailscale
- Mobile app connectivity working (if applicable)
- All service features functional

---

#### Task Group 8: Makerspace & Public Services Migration (Phase 5 & 6)
**Dependencies:** Task Group 7 complete
**Status:** PENDING
**Risk:** High (public-facing services)

**Services:** cchs.makerspace, cchstest, makerspace, kibana, elasticsearch, cerebro, monitoring

- [ ] 8.0 Migrate public and Elasticsearch services
  - [ ] 8.1 Configure permanent Funnel for cchs.makerspace.hcbent.com
    - Enable Tailscale Funnel
    - Obtain Funnel URL
    - Test public access without Tailscale
  - [ ] 8.2 Configure permanent Funnel for kibana.bwortman.us
    - Enable Tailscale Funnel
    - Obtain Funnel URL
    - Test public access without Tailscale
  - [ ] 8.3 Update DNS records for public services
    - Lower TTL to 300s (24 hours before)
    - Update CNAME to Funnel endpoints
    - Verify DNS propagation
  - [ ] 8.4 Verify dual access (public + private)
    - Test public access (no Tailscale)
    - Test private access (via Tailscale)
    - Verify TLS certificates
  - [ ] 8.5 Migrate remaining makerspace services
    - cchstest.home.lab
    - makerspace.home.lab
  - [ ] 8.6 Migrate Elasticsearch stack (4 services)
    - elasticsearch.home.lab
    - cerebro.home.lab
    - monitoring.home.lab (ES monitoring cluster)
  - [ ] 8.7 Document Funnel configuration
  - [ ] 8.8 Test all Elasticsearch functionality

**Acceptance Criteria:**
- 2 services accessible publicly via Funnel
- 2 services also accessible privately via Tailscale
- 5 additional services accessible privately only
- TLS certificates working on public endpoints
- DNS records updated and propagated

---

#### Task Group 9: Final Services Migration (Phase 7)
**Dependencies:** Task Group 8 complete
**Status:** PENDING
**Risk:** Low to moderate

**Services:** argocd, df, dfk

- [ ] 9.0 Migrate remaining services to Tailscale
  - [ ] 9.1 Migrate ArgoCD
    - argocd.home.lab
    - Verify GitOps operations
    - Test sync functionality
  - [ ] 9.2 Migrate DF and DFK
    - df.home.lab
    - dfk.home.lab
    - Verify service functionality
  - [ ] 9.3 Verify all 18 services migrated
    - Create final service inventory
    - Test each service individually
    - Confirm no services left on old architecture
  - [ ] 9.4 Document final migration status

**Acceptance Criteria:**
- All 18 services migrated and accessible
- Service inventory complete and verified
- No services remaining on old infrastructure

---

### PHASE 8: TESTING & VALIDATION (2 WEEKS)

#### Task Group 10: Comprehensive Testing & Monitoring
**Dependencies:** Task Group 9 complete
**Status:** PENDING

- [ ] 10.0 Perform comprehensive validation testing
  - [ ] 10.1 Multi-device testing
    - Test from laptop (macOS/Windows/Linux)
    - Test from phone (iOS/Android)
    - Test from tablet
  - [ ] 10.2 Multi-network testing
    - Test from home WiFi
    - Test from cellular (4G/5G)
    - Test from remote networks
  - [ ] 10.3 Service-specific validation (all 18)
    - Verify each service's core functionality
    - Test data persistence
    - Validate service integrations
  - [ ] 10.4 Performance benchmarking
    - Page load times vs. old architecture
    - Media streaming quality (Plex)
    - File transfer speeds
    - API response times
  - [ ] 10.5 Public service validation
    - Kibana public access (no Tailscale)
    - CCHS Makerspace public access
    - SSL certificate validation
  - [ ] 10.6 Security validation
    - Confirm no port forwarding active
    - Verify private services inaccessible without Tailscale
    - Test ACL policies
    - Review audit logs in Elasticsearch
  - [ ] 10.7 Funnel on-demand workflow testing
    - Enable Funnel for test service
    - Verify public access
    - Disable Funnel
    - Verify access removed
  - [ ] 10.8 Monitoring validation
    - Tailscale metrics in Grafana
    - Alerts configured and functional
    - Metrics populating correctly
  - [ ] 10.9 Create Grafana dashboard for Tailscale
    - Node connectivity status
    - MagicDNS health
    - Funnel availability
    - Connection metrics
  - [ ] 10.10 Configure Prometheus alerts
    - Node disconnection alerts
    - Funnel unavailability alerts
  - [ ] 10.11 Integrate Tailscale audit logs with Elasticsearch
    - Configure log shipping
    - Create Kibana dashboards
  - [ ] 10.12 2-week soak period
    - Monitor for issues
    - Document any problems
    - Resolve critical issues
    - Track stability metrics

**Acceptance Criteria:**
- All devices tested successfully
- All networks tested successfully
- All 18 services validated
- Performance meets or exceeds baseline
- Public services accessible
- Security validation passed
- Monitoring operational
- 2 weeks of stable operation

---

### PHASE 9: INFRASTRUCTURE CLEANUP

#### Task Group 11: Decommission & Documentation
**Dependencies:** Task Group 10 complete (2-week soak successful)
**Status:** PENDING

- [ ] 11.0 Decommission old infrastructure
  - [ ] 11.1 Export NGINX Proxy Manager configuration
    - Export full configuration
    - Save to archive directory
  - [ ] 11.2 Shut down NGINX Proxy Manager
    - Stop container/VM
    - Preserve data for rollback period
  - [ ] 11.3 Remove port forwarding rules
    - Document existing rules
    - Remove from router/firewall
    - Save configuration to archive
  - [ ] 11.4 Update Cloudflare DNS records
    - Remove 16 private service records
    - Keep 2 public records (kibana, cchs)
    - Document changes
  - [ ] 11.5 Verify zero external ports
    - Run nmap scan from external network
    - Verify only expected ports open
  - [ ] 11.6 Archive old configuration
    - NGINX Proxy Manager config
    - Old DNS records
    - Port forwarding rules
    - Cloudflare configurations
  - [ ] 11.7 Maintain 90-day rollback capability
    - Document rollback procedures
    - Preserve archived configs
    - Set reminder for cleanup after 90 days
  - [ ] 11.8 Update infrastructure documentation
    - Network architecture diagrams
    - Service inventory
    - Access procedures
    - Troubleshooting guides
  - [ ] 11.9 Create final migration report
    - Document lessons learned
    - Record any issues encountered
    - Note performance improvements
    - Capture feedback

**Acceptance Criteria:**
- Old infrastructure decommissioned
- Rollback documentation complete
- Zero port forwarding active
- Infrastructure documentation updated
- Migration report completed

---

## Future Enhancements (Post-Migration)

### ACL Policy Tightening
- Implement per-user access controls
- Define service-specific access rules
- Add time-based restrictions
- Enable posture checks

### On-Demand Funnel Management
- Create enable/disable script
- Document temporary sharing workflow
- Test quick disable procedures

### Advanced NGINX Features
- Implement connection pooling
- Add sophisticated health checks
- Configure automatic failover
- Optimize performance tuning

### Advanced Monitoring
- Enhanced Tailscale metrics
- Access pattern analysis
- Performance dashboards
- Predictive alerting

---

## Summary Statistics

**Total Tasks:** 11 task groups
**Total Subtasks:** ~120 individual tasks
**Phases:** 9 (including validation and cleanup)
**Services:** 18 (16 private, 2 public)
**Public Services:** kibana, cchs.makerspace
**Private Services:** 16 services via *.home.lab
**Validation Period:** 2 weeks
**Rollback Window:** 90 days

**Current Status:**
- Phase 0: ✓ COMPLETE (Monitoring verified)
- Phase 1: IN PROGRESS (Task Group 1 ready for user execution)
- Phases 2-9: PENDING
