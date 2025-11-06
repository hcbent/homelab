# Specification: Nginx Load Balancer HA for Kubernetes

## Goal

Deploy a highly available, dual-purpose nginx load balancer cluster that provides failover-protected access to both the Kubernetes API server (control plane nodes) and NodePort services (worker nodes), eliminating single points of failure in cluster access.

## User Stories

- As a cluster administrator, I want automatic failover for Kubernetes API access so that control plane node failures do not interrupt cluster management operations
- As a developer, I want reliable access to NodePort services through a stable endpoint so that application availability is maintained during node failures
- As an infrastructure operator, I want a self-healing load balancer infrastructure so that manual intervention is not required during node failures

## Specific Requirements

**Two-Node HA Cluster with Corosync/Pacemaker**
- Deploy two nginx load balancer VMs (nginx-lb01 at 192.168.10.251, nginx-lb02 at 192.168.10.252)
- Implement Corosync for cluster communication and membership management
- Configure Pacemaker for VIP resource management at 192.168.10.250
- Use two_node: 1 quorum policy for 2-node cluster operation
- Disable STONITH (acceptable for homelab environment)
- Configure nginx-lb01 as preferred primary node with automatic failback
- Split VMs across different Proxmox hosts (pve1 and pve2) for true hypervisor-level HA

**Kubernetes API Server Load Balancing (Layer 4)**
- Load balance port 6443 traffic to all three control plane nodes (kube01: 192.168.10.11, kube02: 192.168.10.12, kube03: 192.168.10.13)
- Use TCP stream mode (Layer 4) for end-to-end TLS passthrough
- Implement least_conn load balancing algorithm for fair connection distribution
- Configure health checks: max_fails=2, fail_timeout=30s
- Set proxy_timeout=10m and proxy_connect_timeout=10s for long-lived kubectl operations
- Maintain certificate validation from clients directly to API servers
- Preserve client certificate authentication for RBAC

**NodePort Services Load Balancing (Layer 7)**
- Load balance NodePort services to worker nodes only (kube04: 192.168.10.14, kube05: 192.168.10.15, kube06: 192.168.10.16)
- Use HTTP/HTTPS proxy mode (Layer 7) with full header forwarding
- Configure initial services: ArgoCD (8080/8443 -> 31160/32442), Traefik (80/443 -> 31469/31685)
- Include WebSocket support with HTTP/1.1 upgrade headers
- Use least_conn algorithm for NodePort upstreams
- Configure health checks: max_fails=2, fail_timeout=30s
- Make configuration extensible for adding new NodePort services

**Terraform Infrastructure Provisioning**
- Create new module at tf/nginx-lb/ using existing proxmox_vm module pattern
- Provision two VMs with: 2 cores, 2GB RAM, 20GB disk, Ubuntu 25.04 template
- Configure static IPs: 192.168.10.251 (nginx-lb01), 192.168.10.252 (nginx-lb02)
- Deploy nginx-lb01 to pve1, nginx-lb02 to pve2 for anti-affinity
- Use "tank" NFS storage backend for VM disks
- Integrate with HashiCorp Vault for SSH keys and cloud-init credentials
- Assign VMIDs 250 and 251 for nginx-lb01 and nginx-lb02
- Tag VMs with: "nginx;loadbalancer;ha"

**Ansible Configuration Management**
- Create playbook to install nginx, corosync, and pacemaker on both nodes
- Deploy dual-purpose nginx configuration from Jinja2 templates
- Configure corosync cluster with VIP (192.168.10.250) as cluster resource
- Set up automatic failover with preferred primary node configuration
- Update kubeconfig on remote cluster nodes to use VIP endpoint (192.168.10.250:6443)
- Create new inventory group [nginx_lb] with both nodes
- Define group variables for VIP (192.168.10.250) and cluster_name (nginx-lb-cluster)
- Ensure playbook idempotency for safe re-runs and configuration updates

**Kubeconfig Update Management**
- Automate kubeconfig updates on all remote cluster nodes via Ansible
- Backup existing kubeconfig files before modification
- Update server endpoint to https://192.168.10.250:6443
- Validate connectivity after update
- Provide manual instructions for local workstation kubeconfig updates
- Include rollback procedures in documentation

**Health Monitoring and Validation**
- Implement nginx passive health checks for backend availability
- Configure dedicated health check endpoint at port 8888/health
- Validate VIP accessibility and failover behavior
- Test kubectl operations through load balancer
- Verify NodePort service accessibility through load balancer
- Ensure monitoring integration points for existing Prometheus/Grafana stack

## Visual Design

No visual assets provided for this infrastructure feature.

## Existing Code to Leverage

**tf/modules/proxmox_vm/ - Shared VM Provisioning Module**
- Provides standardized Proxmox VM provisioning with cloud-init support
- Handles cloud-init configuration, SSH key deployment, network setup
- Includes prevent_destroy lifecycle and comprehensive ignore_changes
- Configure serial console for Proxmox web console compatibility
- Use this module for both nginx-lb01 and nginx-lb02 provisioning

**tf/kubernetes/ - Kubernetes Cluster Terraform Pattern**
- Follow the same structure: main.tf, variables.tf, outputs.tf, provider.tf, versions.tf, terraform.tfvars
- Use Vault integration pattern via data.vault_kv_secret_v2 resources
- Replicate the list-based VM definition pattern from kubernetes_vms variable
- Apply the same cloud-init user configuration approach

**tf/nginx-lb/ - Existing Skeleton Module**
- Initial Terraform configuration already exists at tf/nginx-lb/
- Current main.tf provisions single VM, needs enhancement for two-node cluster
- Existing Vault integration for SSH keys and credentials already configured
- Extend terraform.tfvars to define both nginx-lb01 and nginx-lb02 VMs
- Update to use list-based pattern similar to kubernetes cluster

**ansible/playbooks/setup_nginx_lb.yml - Existing Nginx Playbook**
- Current playbook targets nginx_lb inventory group (already compatible)
- Implements nginx installation, configuration from template, and service management
- Uses ansible/templates/nginx-lb.conf.j2 for configuration generation
- Needs enhancement for: Kubernetes API stream block, corosync/pacemaker installation, HA configuration
- Extend k8s_workers variable to include both control plane and worker node definitions

**ansible/templates/nginx-lb.conf.j2 - Existing Nginx Configuration Template**
- Current template implements HTTP proxy for NodePort services (Layer 7)
- Includes WebSocket support, proper headers, timeouts, and health checks
- Uses Jinja2 templating for dynamic upstream generation from variables
- Needs addition of: stream block for K8s API passthrough, separation of control plane and worker backends
- Leverage existing upstream pattern and health check configuration

## Out of Scope

- Three-node or larger HA clusters (two nodes sufficient for homelab)
- Active-active load balancing with BGP/ECMP (active-passive with VIP is sufficient)
- SSL/TLS termination at load balancer (passthrough mode only)
- Automated local workstation kubeconfig updates (manual only for security)
- Dynamic NodePort service discovery and configuration
- WAF (Web Application Firewall) capabilities
- DDoS protection or advanced rate limiting
- External load balancer services or cloud provider integrations
- DNS-based load balancing or service discovery
- Global server load balancing (GSLB)
- Advanced monitoring beyond existing Prometheus/Grafana integration
- Automated certificate generation or management (handled by existing step-certificates)
- Load balancing for services outside Kubernetes cluster
- Integration with service mesh features
