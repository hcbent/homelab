# Product Mission

## Pitch
Homelab Tailscale Migration is a comprehensive networking transformation project that helps homelab infrastructure operators modernize their networking architecture by migrating from traditional port forwarding and reverse proxy setups to a zero-trust Tailscale mesh network, providing enhanced security, simplified management, and seamless private access to homelab services.

## Users

### Primary Customers
- **Homelab Infrastructure Operators**: Individuals managing self-hosted Kubernetes clusters and multiple private services seeking to improve security and simplify network architecture
- **Privacy-Focused Self-Hosters**: Technical users who prioritize secure, encrypted access to their services without exposing them to the public internet
- **DevOps Engineers**: Professionals testing zero-trust networking patterns in home environments before implementing in production

### User Personas

**Homelab Network Administrator** (30-50 years old)
- **Role:** Infrastructure operator managing multi-node Kubernetes cluster with 10+ services
- **Context:** Currently using Cloudflare DNS with NGINX Proxy Manager for routing traffic to services, concerned about attack surface and management complexity
- **Pain Points:**
  - Port forwarding creates security vulnerabilities and exposes services to internet scanning
  - NGINX Proxy Manager requires manual configuration for each service
  - Cloudflare tunnel setup is complex and creates external dependencies
  - No unified access control across all services
  - Difficult to securely share temporary access to services
  - Managing TLS certificates and DNS records is time-consuming
- **Goals:**
  - Eliminate public exposure of private services (Sonarr, Radarr, qBittorrent, Actual Budget)
  - Maintain public access only for services that require it (Kibana, CCHS Makerspace)
  - Implement zero-trust networking with encrypted mesh
  - Simplify service access with clean internal URLs instead of IP:port combinations
  - Enable secure, temporary service sharing when needed
  - Reduce management overhead and external dependencies

**Security-Conscious Infrastructure Engineer** (25-45 years old)
- **Role:** DevOps engineer or SRE learning zero-trust networking in home environment
- **Context:** Operating Kubernetes cluster with production-grade tooling (Terraform, Ansible, Vault), wants to implement enterprise security patterns at home
- **Pain Points:**
  - Traditional reverse proxy architecture doesn't align with zero-trust principles
  - Cannot easily implement granular access control per service
  - Exposing services through port forwarding creates unnecessary risk
  - No visibility into who accesses what services
  - Cloudflare dependency creates single point of failure
  - Difficult to test zero-trust patterns without enterprise tools
- **Goals:**
  - Implement true zero-trust networking with encrypted WireGuard mesh
  - Use MagicDNS for service discovery without manual DNS management
  - Integrate with existing infrastructure automation (Kubernetes, Helm, Vault)
  - Learn Tailscale deployment patterns applicable to work environments
  - Maintain infrastructure-as-code approach for all networking changes
  - Achieve end-to-end encryption for all service access

## The Problem

### Exposed Attack Surface from Traditional Port Forwarding
Current homelab setups typically expose services through port forwarding and reverse proxies, creating a large attack surface. Every exposed port is constantly scanned by automated tools, leading to brute force attempts, vulnerability exploitation, and potential data breaches. Port 443 traffic is inspected, logged, and targeted by malicious actors.

**Our Solution:** Tailscale mesh network keeps all services private by default, accessible only through encrypted WireGuard VPN connections. Only explicitly designated services (Kibana, CCHS Makerspace) are exposed via Tailscale Funnel, dramatically reducing attack surface from 10+ services to 2 controlled endpoints.

### Complex Multi-Layer Networking Architecture
Traditional homelab networking involves Cloudflare DNS, port forwarding rules, NGINX Proxy Manager configurations, internal DNS records, and manual TLS certificate management. Each layer requires separate configuration, creating opportunities for misconfigurations and making changes time-consuming and error-prone.

**Our Solution:** Unified Tailscale-based architecture with MagicDNS for automatic service discovery, built-in WireGuard encryption, and Funnel for public access when needed. Single configuration point replaces multiple disconnected systems, reducing complexity by 70%.

### No Unified Access Control or Audit Trail
Current reverse proxy setups provide no visibility into who accesses services, when, or from where. Access control is binary (public or private), with no ability to implement granular permissions per user or service. Temporary service sharing requires creating permanent access rules.

**Our Solution:** Tailscale ACLs provide centralized access control with per-user, per-service permissions. MagicDNS ensures consistent naming across all devices. Tailscale Funnel enables on-demand public access for temporary sharing without reconfiguring infrastructure. Complete audit logs show all access attempts.

### Dependency on External Services and DNS Providers
Cloudflare dependency creates single point of failure - if Cloudflare has issues, homelab services become inaccessible. DNS propagation delays make configuration changes slow. Managing external DNS records requires separate tooling and accounts outside homelab infrastructure.

**Our Solution:** Tailscale mesh network provides direct peer-to-peer connectivity between devices, removing external dependencies for private service access. MagicDNS operates within the tailnet without requiring public DNS records. Services remain accessible even if external DNS providers experience outages.

## Differentiators

### Zero-Trust Mesh Network for Homelab Scale
Unlike traditional reverse proxy architectures that create DMZs and perimeter security, we implement true zero-trust networking where every connection is authenticated, encrypted, and authorized. This results in enterprise-grade security at homelab scale without complex firewall rules or VPN server maintenance.

### Seamless Integration with Existing Kubernetes Infrastructure
Unlike standalone VPN solutions that require separate management, we deploy Tailscale natively in Kubernetes as part of the existing infrastructure-as-code workflow. This results in GitOps-managed networking integrated with Terraform, Ansible, Vault, and ArgoCD for consistent automation.

### Selective Public Access via Tailscale Funnel
Unlike all-or-nothing approaches that force services to be either completely public or completely private, we use Tailscale Funnel to expose specific services (Kibana, CCHS Makerspace) publicly while keeping all other services private. This results in minimal attack surface with flexibility for legitimate public access.

### Infrastructure-as-Code Networking Migration
Unlike manual VPN configuration or GUI-based network changes, every aspect of this migration is defined in version-controlled code with Kubernetes manifests, Helm charts, and Terraform configurations. This results in reproducible networking changes that can be audited, rolled back, and documented automatically.

## Key Features

### Tailscale Mesh Network Deployment
- **Kubernetes Integration:** Deploy Tailscale operator or DaemonSet across Kubernetes cluster (km01, km02, km03) with automatic node registration and mesh network formation
- **MagicDNS Configuration:** Enable automatic DNS resolution for all Tailscale-connected devices with clean internal hostnames (sonarr.home.lab instead of 192.168.10.45:8989)
- **Vault Secret Integration:** Store Tailscale auth keys in HashiCorp Vault and retrieve dynamically during deployment for secure, automated authentication

### Private Service Access
- **Internal NGINX Proxy:** Deploy lightweight NGINX (not Proxy Manager) within Kubernetes for URL-based routing to services using clean hostnames
- **Service Migration:** Configure all private services (Sonarr, Radarr, qBittorrent, Actual Budget, Home Assistant, Pi-hole, Plex) to be accessible only via Tailscale mesh
- **Access Control Lists:** Define Tailscale ACL policies specifying which users and devices can access which services within the tailnet

### Public Service Exposure
- **Permanent Funnel Configuration:** Set up always-on Tailscale Funnel for kibana.bwortman.us and cchs.makerspace.hcbent.com providing public HTTPS access through Tailscale infrastructure
- **DNS Migration:** Update DNS records from Cloudflare-managed to Tailscale-managed hostnames for public services
- **Certificate Management:** Leverage Tailscale's automatic HTTPS certificates for Funnel endpoints, eliminating manual TLS management

### On-Demand Service Sharing
- **Funnel On-Demand:** Document and enable procedures for temporarily exposing any service via Tailscale Funnel for single-user sharing scenarios
- **Temporary Access Links:** Generate time-limited Funnel URLs for sharing services with collaborators or clients without permanent public exposure
- **Access Revocation:** Quick disable procedures for removing public access after sharing period ends

### Service Discovery & DNS
- **MagicDNS Setup:** Configure MagicDNS across tailnet for automatic hostname resolution without manual DNS configuration
- **Internal Domain:** Establish internal domain naming convention (e.g., home.lab) for all Tailscale-accessible services
- **DNS Resolution Order:** Configure Tailscale devices to prioritize MagicDNS for internal services while maintaining external DNS for internet access

### Monitoring & Observability
- **Tailscale Metrics:** Integrate Tailscale connection status and metrics into existing Prometheus/Grafana monitoring stack
- **Connection Health:** Monitor mesh network connectivity, node status, and Funnel availability with automated alerts
- **Access Logging:** Enable Tailscale audit logging and integrate with Elasticsearch/Kibana for centralized access visibility

### Infrastructure Cleanup
- **NGINX Proxy Manager Decommission:** Safely remove old NGINX Proxy Manager after validating all services accessible via Tailscale
- **Port Forwarding Removal:** Eliminate all port forwarding rules on network router/firewall after migration complete
- **Cloudflare Cleanup:** Remove or update Cloudflare DNS records for services now managed by Tailscale

### Documentation & Runbooks
- **Access Instructions:** Create user documentation for connecting to Tailscale and accessing homelab services from any device
- **Service Catalog:** Document all services with their new Tailscale URLs, access requirements, and connection procedures
- **Troubleshooting Guide:** Build runbooks for common issues (connection failures, DNS resolution problems, Funnel configuration)
- **Rollback Procedures:** Document step-by-step rollback to previous Cloudflare/NGINX architecture if needed during migration

## Success Criteria

### Security Improvements
- Zero port forwarding rules on external firewall (down from 10+)
- All private services accessible only through encrypted Tailscale mesh
- Complete audit trail of service access showing user, timestamp, and source
- Public service exposure limited to 2 controlled endpoints (Kibana, CCHS Makerspace)

### Management Simplification
- Single configuration point (Tailscale ACLs) for all network access control
- No manual DNS record management for internal services
- Automatic TLS certificate management via Tailscale Funnel
- 70% reduction in networking configuration complexity

### Infrastructure Integration
- Tailscale deployment managed via GitOps (ArgoCD) like all other infrastructure
- Tailscale auth keys stored in Vault following existing secret management patterns
- Monitoring integrated into existing Prometheus/Grafana stack
- All networking changes version-controlled and reproducible

### User Experience
- Access all services via clean URLs (service.home.lab) instead of IP:port combinations
- Connect from any device (laptop, phone, tablet) after one-time Tailscale setup
- Seamless roaming between networks (home, work, mobile) without connection changes
- Temporary service sharing accomplished in under 5 minutes

### Operational Excellence
- Complete rollback capability to previous architecture if issues arise
- Documented runbooks for common operations (adding services, sharing access, troubleshooting)
- Zero downtime for critical services during migration
- Infrastructure-as-code for all Tailscale configurations enabling disaster recovery
