# Product Roadmap

## Tailscale Migration Roadmap

This roadmap outlines the comprehensive migration from Cloudflare + NGINX Proxy Manager architecture to a Tailscale-based zero-trust mesh network. Features are ordered by technical dependencies and designed to enable incremental validation while maintaining service availability throughout the migration.

### Phase 1: Foundation & Setup

1. [ ] Tailscale Account Configuration — Set up Tailscale tailnet with admin access, configure organization settings, enable MagicDNS globally, and create initial ACL policy structure for homelab services. `XS`

2. [ ] Vault Integration for Tailscale Secrets — Generate Tailscale auth keys (reusable, tagged for Kubernetes nodes), store in HashiCorp Vault under `secret/tailscale/auth-keys`, and create Vault policy for Kubernetes secret retrieval. `XS`

3. [ ] Tailscale Kubernetes Deployment — Deploy Tailscale operator or DaemonSet to Kubernetes cluster (km01, km02, km03) using Helm chart, configure to retrieve auth keys from Vault, and verify all nodes appear in tailnet with MagicDNS hostnames. `S`

4. [ ] MagicDNS Validation — Test DNS resolution from Tailscale-connected devices to Kubernetes nodes, verify MagicDNS working for node-to-node communication, and document internal hostname patterns (km01.tail-xxxxx.ts.net). `XS`

5. [ ] Client Device Setup — Install Tailscale on primary client devices (laptop, phone), authenticate to tailnet, verify MagicDNS resolution to Kubernetes nodes, and document connection procedures for future users. `XS`

### Phase 2: Internal NGINX & Service Discovery

6. [ ] Internal NGINX Deployment — Deploy standard NGINX (not Proxy Manager) to Kubernetes cluster as NodePort service, create ConfigMap-based configuration for URL routing, and set up basic routing rules for test services. `S`

7. [ ] Service Discovery Configuration — Configure internal DNS naming convention (home.lab domain), create NGINX upstream definitions for all homelab services (Sonarr, Radarr, qBittorrent, Actual Budget, etc.), and implement hostname-based routing (sonarr.home.lab, radarr.home.lab). `M`

8. [ ] Local DNS Integration — Configure Tailscale DNS settings to resolve *.home.lab to NGINX service IP within tailnet, test resolution from all client devices, and verify clean URL access to services via Tailscale mesh. `S`

9. [ ] Service Health Checks — Implement NGINX health checks for all upstream services, configure automatic failover for multi-replica services, and set up connection pooling and timeout settings. `S`

### Phase 3: Private Service Migration

10. [ ] Media Services Migration — Migrate Sonarr, Radarr, qBittorrent, and Jackett to Tailscale-only access, update NGINX routing for media services, verify functionality via service.home.lab URLs, and document new access patterns. `M`

11. [ ] Home Automation Migration — Migrate Home Assistant, Pi-hole, and other home automation services to Tailscale access, configure NGINX routing, test mobile app connectivity via Tailscale, and update any service integrations. `M`

12. [ ] Productivity Services Migration — Migrate Actual Budget, Mealie, Paperless-ngx, and CopyParty to Tailscale access, configure NGINX routing, test all web interfaces, and verify file upload/download functionality. `M`

13. [ ] Plex Media Server Migration — Configure Plex for Tailscale access, update NGINX routing with appropriate buffer settings for streaming, test video playback from multiple devices, and verify remote access functionality. `M`

14. [ ] ACL Policy Implementation — Define granular Tailscale ACL policies for service access control, implement user-based access restrictions if needed, test ACL enforcement, and document policy structure. `S`

### Phase 4: Public Service Configuration

15. [ ] Kibana Funnel Setup — Configure permanent Tailscale Funnel for kibana.bwortman.us, verify HTTPS certificate provisioning, test public accessibility without Tailscale connection, and validate Elasticsearch backend connectivity. `M`

16. [ ] CCHS Makerspace Funnel Setup — Configure permanent Tailscale Funnel for cchs.makerspace.hcbent.com, verify HTTPS certificate provisioning, test public accessibility, and validate application functionality via Funnel endpoint. `M`

17. [ ] DNS Record Migration — Update DNS records for kibana.bwortman.us and cchs.makerspace.hcbent.com to point to Tailscale Funnel URLs, configure appropriate TTLs for quick rollback if needed, and monitor DNS propagation. `S`

18. [ ] Public Service Validation — Comprehensive testing of public service access from non-Tailscale devices, verify TLS certificate validity, test from multiple networks and geographic locations, and validate performance. `S`

### Phase 5: Monitoring & Observability

19. [ ] Tailscale Metrics Integration — Deploy Tailscale Prometheus exporter (if available) or implement custom metrics collection, integrate into existing Prometheus stack, and create Grafana dashboard for Tailscale connectivity status. `M`

20. [ ] Connection Health Monitoring — Configure alerts for Kubernetes node disconnections from tailnet, monitor MagicDNS resolution failures, track Funnel availability for public services, and set up notification channels. `S`

21. [ ] Access Logging — Enable Tailscale audit logging in admin console, configure log export to Elasticsearch if supported, create Kibana dashboards for access patterns, and document log retention policies. `S`

22. [ ] NGINX Metrics Integration — Enable NGINX Prometheus exporter, collect metrics for request rates, response times, and upstream health, create Grafana dashboards for service access patterns, and configure performance alerts. `S`

### Phase 6: Testing & Validation

23. [ ] End-to-End Service Testing — Comprehensive functional testing of all services from Tailscale-connected devices, verify all URLs resolve correctly, test from multiple device types (laptop, phone, tablet), and document any issues. `M`

24. [ ] Performance Validation — Benchmark service response times via Tailscale vs. previous architecture, test video streaming quality through Plex, measure file transfer speeds for media downloads, and identify any bottlenecks. `S`

25. [ ] Failover Testing — Simulate Kubernetes node failures and verify Tailscale reconnection, test NGINX upstream failover for multi-replica services, validate MagicDNS resolution during network changes, and document recovery times. `M`

26. [ ] On-Demand Sharing Test — Practice enabling Tailscale Funnel for temporary service sharing, test access from non-Tailscale devices, verify quick disable procedures, and document workflow for future sharing needs. `S`

27. [ ] Security Validation — Review all Tailscale ACL policies for least-privilege access, verify no unintended service exposure, test audit logging completeness, and conduct security review of new architecture. `M`

### Phase 7: Infrastructure Cleanup

28. [ ] NGINX Proxy Manager Decommission — Verify all services migrated and accessible via Tailscale, export any required configuration for reference, safely shut down NGINX Proxy Manager, and remove Kubernetes deployment. `S`

29. [ ] Port Forwarding Removal — Document all existing port forwarding rules for reference, remove port forwards from router/firewall, verify external port scanning shows no open ports, and validate private services inaccessible from internet. `S`

30. [ ] Cloudflare Configuration Update — Remove or update Cloudflare DNS records for migrated private services, retain records only for services still using Cloudflare (if any), document final Cloudflare configuration, and archive old DNS zone files. `S`

31. [ ] Network Architecture Documentation — Create network diagrams showing new Tailscale-based architecture, document all service URLs and access patterns, update infrastructure repository README with Tailscale information, and archive old architecture documentation. `M`

### Phase 8: Documentation & Knowledge Transfer

32. [ ] User Access Guide — Write comprehensive guide for connecting to Tailscale, accessing homelab services, troubleshooting common connection issues, and onboarding new users to the tailnet. `S`

33. [ ] Service Catalog Creation — Document all services with Tailscale URLs, access requirements, service dependencies, and connection instructions. Create searchable catalog for quick reference. `S`

34. [ ] Operational Runbooks — Create runbooks for common operations: adding new services, configuring Funnel for sharing, troubleshooting DNS resolution, handling node disconnections, and rotating Tailscale auth keys. `M`

35. [ ] Rollback Documentation — Document complete rollback procedures to previous Cloudflare/NGINX architecture, including step-by-step instructions, configuration backups needed, and estimated rollback time. Maintain for 90 days post-migration. `S`

36. [ ] Infrastructure-as-Code Updates — Commit all Tailscale Kubernetes manifests to git repository, create ArgoCD application for Tailscale deployment, document Terraform/Ansible integration points, and ensure reproducible deployment. `M`

> Notes
> - Order follows technical dependencies: setup → internal networking → private services → public services → monitoring → validation → cleanup → documentation
> - Each phase builds on previous phases to enable incremental validation
> - Migration maintains service availability throughout - no big-bang cutover required
> - Rollback capability maintained until Phase 7 cleanup begins
> - Focus on infrastructure-as-code ensures all changes are reproducible and version-controlled
> - Effort estimates account for both implementation and validation time
> - Public services (Kibana, CCHS Makerspace) migrated after private services proven working
> - Monitoring and observability integrated early to provide visibility throughout migration
> - Documentation created throughout process, not as afterthought
> - Total estimated timeline: 6-8 weeks with incremental progress and validation
