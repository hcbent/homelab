# Kubespray Configuration Decisions

This document explains the key configuration decisions made for the homelab kubespray Kubernetes cluster deployment.

## Table of Contents
- [Overview](#overview)
- [Kubernetes Version](#kubernetes-version)
- [Container Runtime](#container-runtime)
- [Network Plugin (CNI)](#network-plugin-cni)
- [Etcd Configuration](#etcd-configuration)
- [DNS Configuration](#dns-configuration)
- [Add-ons Strategy](#add-ons-strategy)
- [Load Balancing](#load-balancing)
- [Storage](#storage)
- [Security Considerations](#security-considerations)

---

## Overview

This kubespray cluster is designed for homelab use with the following topology:
- **Control Plane Nodes**: 3 nodes (km01 bare metal, km02-km03 VMs)
- **Worker Nodes**: 3 nodes (kube01-kube03 VMs)
- **Network**: 192.168.10.0/24 physical, 10.233.0.0/18 services, 10.233.64.0/18 pods
- **Storage Backend**: FreeNAS via Democratic CSI (iSCSI/NFS)
- **Deployment Method**: Kubespray via Ansible

---

## Kubernetes Version

**Choice**: `v1.29.5`

**Rationale**:
- Kubernetes 1.29 is a stable, production-ready release
- Provides modern features while maintaining stability
- Well-supported by kubespray and the Kubernetes ecosystem
- Includes critical features like graceful node shutdown, improved scheduling, and enhanced observability

**Alternatives Considered**:
- v1.28.x: Previous stable version, but v1.29 offers improvements
- v1.30.x: Newer but less mature, may have undiscovered issues
- v1.31.x: Too new for production homelab use

**Update Strategy**:
- Minor version upgrades (e.g., 1.29.5 → 1.29.6) can be done with low risk
- Major version upgrades (e.g., 1.29 → 1.30) should be tested and planned
- Always review kubespray and Kubernetes release notes before upgrading

---

## Container Runtime

**Choice**: `containerd`

**Rationale**:
- **Industry Standard**: Containerd is the de facto container runtime for Kubernetes
- **Lightweight**: Lower resource overhead compared to Docker
- **Native CRI Support**: Built specifically for Kubernetes Container Runtime Interface
- **Simplicity**: No need for Docker daemon, reducing complexity
- **Deprecation**: Docker's dockershim is deprecated in Kubernetes 1.20+
- **Performance**: Better performance and resource efficiency than Docker

**Configuration Highlights**:
- Storage: `/var/lib/containerd`
- Runtime: `runc` (default OCI runtime)
- GRPC limits: 16MB message size
- Log line limit: 16KB to prevent huge log entries
- OOM score: 0 (prevents containerd from being killed by OOM killer)

**Alternatives Considered**:
- **CRI-O**: Another lightweight runtime, but containerd has wider adoption
- **Docker**: Deprecated for Kubernetes use, more resource-intensive

---

## Network Plugin (CNI)

**Choice**: `Calico`

**Rationale**:
- **Novice-Friendly**: Extensive documentation and large community
- **NetworkPolicy Support**: Built-in support for Kubernetes NetworkPolicies
- **Performance**: Good performance for small to medium clusters
- **Troubleshooting**: Well-documented troubleshooting procedures
- **Features**: BGP routing, IP-in-IP tunneling, and flexible networking options
- **Stability**: Mature, battle-tested CNI plugin

**Configuration Highlights**:
- Pod network: `10.233.64.0/18`
- Service network: `10.233.0.0/18`
- Node prefix: `/24` (~254 pods per node)
- IPAM: Calico IPAM for pod IP allocation
- Dataplane: iptables mode (can switch to eBPF in future)

**Alternatives Considered**:
- **Flannel**: Simpler but fewer features (no NetworkPolicy support)
- **Cilium**: More advanced (eBPF-based) but steeper learning curve
- **Weave**: Legacy option, less active development

**Integration with MetalLB**:
- `kube_proxy_strict_arp: true` is set to ensure MetalLB works correctly in Layer 2 mode
- This prevents nodes from responding to ARP requests for service IPs

---

## Etcd Configuration

**Choice**: Stacked etcd topology with 3 members

**Rationale**:
- **High Availability**: 3-member cluster can tolerate 1 node failure
- **Quorum**: With 3 members, quorum = 2 (majority consensus)
- **Simplicity**: Stacked etcd (on control plane nodes) is simpler than external etcd
- **Resource Efficiency**: No need for dedicated etcd VMs
- **Standard Practice**: Stacked etcd is the recommended approach for clusters < 100 nodes

**Configuration Highlights**:
- **Deployment Type**: `host` (systemd service, not containerized)
- **Data Directory**: `/var/lib/etcd`
- **Memory Limit**: 2048M (2GB) per etcd member
- **Quota Backend**: 2GB maximum database size
- **Members**: km01, km02, km03 (all control plane nodes)

**Why `host` deployment instead of containerized**:
- Better performance (no container overhead)
- Easier to debug and manage with systemd
- More stable and predictable resource usage
- Standard practice for production clusters

**Backup Strategy**:
- Manual backups documented in `docs/KUBESPRAY-BACKUP-RESTORE.md`
- Recommended: Daily automated snapshots to NAS
- Retention: Keep last 7 days of snapshots

**Failure Scenarios**:
- **1 node failure**: Cluster continues operating (2/3 quorum)
- **2 node failures**: Cluster enters read-only mode (no quorum)
- **3 node failures**: Complete cluster failure, restore from backup

---

## DNS Configuration

**Choice**: CoreDNS with NodeLocal DNS cache

**Rationale**:
- **CoreDNS**: Modern, flexible DNS server for Kubernetes (default since K8s 1.13)
- **NodeLocal DNS**: Caches DNS queries on each node for better performance
- **Reduced Latency**: Local caching reduces DNS query time significantly
- **Reduced Load**: Less load on CoreDNS pods

**Configuration Highlights**:
- DNS mode: `coredns`
- NodeLocal DNS: Enabled
- NodeLocal IP: `169.254.25.10` (link-local address)
- Upstream DNS: `192.168.10.1` (homelab gateway/Pi-hole)
- Cluster domain: `homelab-kubespray`
- ndots: 2

**How NodeLocal DNS Works**:
1. Pod DNS queries go to local cache at 169.254.25.10
2. Cache hits are served immediately
3. Cache misses are forwarded to CoreDNS pods
4. External queries are forwarded to upstream DNS (192.168.10.1)

**Benefits**:
- Faster DNS resolution for frequently accessed domains
- Reduced DNS latency for service discovery
- Lower network traffic to CoreDNS pods
- Better DNS availability (local cache survives CoreDNS pod restarts)

---

## Add-ons Strategy

**Philosophy**: Minimal kubespray add-ons, deploy most components via ArgoCD

**Rationale**:
- **GitOps-First**: ArgoCD enables declarative, version-controlled application management
- **Flexibility**: Easier to customize and update components deployed via ArgoCD
- **Separation of Concerns**: Cluster infrastructure (kubespray) vs. platform components (ArgoCD)
- **Easier Rollbacks**: Git-based rollbacks for application changes

### Enabled in Kubespray:
- **Helm**: Required for Helm-based deployments (`helm_enabled: true`)
- **Metrics Server**: Required for HPA and `kubectl top` (`metrics_server_enabled: true`)
- **Cert-manager**: Required for certificate management (`cert_manager_enabled: true`)

### Disabled in Kubespray (deployed via ArgoCD instead):
- **MetalLB**: Load balancer (`metallb_enabled: false`)
- **Ingress-NGINX**: Ingress controller - using Traefik (`ingress_nginx_enabled: false`)
- **Local Storage Provisioners**: Using Democratic CSI (`local_path_provisioner_enabled: false`)
- **Kubernetes Dashboard**: Using alternative tools (`dashboard_enabled: false`)
- **ArgoCD**: Bootstrapped manually after cluster deployment

**Why cert-manager is enabled in kubespray**:
- Requires CRDs installed early in cluster lifecycle
- Used immediately for internal certificate management
- Difficult to bootstrap via ArgoCD without existing cert infrastructure

**Why metrics-server is enabled**:
- Core cluster component needed for basic Kubernetes functionality
- Required for HPA (Horizontal Pod Autoscaler)
- Required for `kubectl top` commands
- Low overhead, stable component

---

## Load Balancing

**Choice**: MetalLB in Layer 2 mode (deployed via ArgoCD)

**Rationale**:
- **Bare Metal**: MetalLB is the standard for LoadBalancer services on bare metal
- **Layer 2 Mode**: Simpler than BGP mode, suitable for homelab single-network topology
- **IP Pool**: Using `192.168.100.0/24` range for LoadBalancer service IPs
- **ARP-based**: Uses ARP to announce service IPs on local network

**Configuration Requirements**:
- `kube_proxy_strict_arp: true` must be set (already configured)
- IP pool must not conflict with DHCP or static IPs
- Network must support ARP (works on standard Ethernet networks)

**Deployment via ArgoCD**:
- Helm chart: `metallb/metallb`
- Resources: IPAddressPool, L2Advertisement
- Managed declaratively in Git repository

---

## Storage

**Choice**: Democratic CSI with FreeNAS backend (iSCSI + NFS)

**Rationale**:
- **Integration**: Leverages existing FreeNAS "tank" storage pool
- **Protocols**: iSCSI for block storage, NFS for shared storage
- **Dynamic Provisioning**: Automatic PVC provisioning and deletion
- **ZFS Features**: Benefits from ZFS compression, snapshots, and replication
- **Cost-Effective**: Uses existing NAS infrastructure

**Storage Classes**:
- `freenas-iscsi-csi`: Default storage class for block storage (RWO)
- `freenas-nfs-csi`: Shared storage for RWX workloads

**Why not local storage**:
- No data persistence if node fails
- Can't migrate pods between nodes with data
- No centralized backup/snapshot capability

**Deployment**:
- Deployed via Helm after cluster initialization
- Credentials retrieved from Vault (`secret/homelab/freenas/credentials`)
- iSCSI initiator installed on all worker nodes

---

## Security Considerations

### Secrets Management
- **Vault Integration**: All credentials stored in HashiCorp Vault
- **No Plain Text Secrets**: Terraform and Ansible retrieve secrets from Vault
- **Vault Server**: `https://192.168.10.101:8200`

### Network Security
- **Calico NetworkPolicies**: Can implement namespace isolation
- **Service Mesh**: Not implemented initially (can add Istio/Linkerd later)
- **Ingress TLS**: Internal CA via cert-manager, external via NGINX Proxy Manager

### Certificate Management
- **Internal CA**: Cert-manager with self-signed ClusterIssuer
- **External TLS**: NGINX Proxy Manager handles Let's Encrypt
- **Certificate Rotation**: Automated via cert-manager

### API Server Access
- **Local Load Balancer**: Nginx load balancer on each node for HA API access
- **Port**: 6443 (standard Kubernetes API port)
- **mTLS**: Mutual TLS between all cluster components

### RBAC
- **Default RBAC**: Kubespray configures secure RBAC policies
- **Service Accounts**: Custom service accounts for applications
- **Least Privilege**: Applications should use minimal RBAC permissions

### Encryption at Rest
- **Not Enabled**: `kube_encrypt_secret_data: false`
- **Rationale**: Homelab environment, less critical than production
- **Future**: Can enable if storing sensitive data in cluster

---

## Configuration File Locations

All configuration files are stored in the homelab repository:

```
kubespray/inventory/homelab/
├── hosts.ini                                    # Inventory file
├── group_vars/
│   ├── all/
│   │   ├── all.yml                             # Common variables
│   │   └── etcd.yml                            # Etcd configuration
│   └── k8s_cluster/
│       ├── k8s-cluster.yml                     # Main cluster config
│       ├── addons.yml                          # Addon selection
│       └── k8s-net-containerd.yml             # Containerd config
└── host_vars/                                  # Host-specific overrides (if needed)
```

---

## Known Issues and Fixes

### Calico CRD Checksum Mismatch (Fixed)

**Issue**: Kubespray 3.30.3 contains an incorrect checksum for the Calico CRDs tarball, causing deployment failures during the download phase.

**Symptoms**:
- Deployment fails at "Download_file | Download item" task
- Error: `fatal: [control-plane-nodes]: FAILED! => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result"}`
- Downloads fail after ~24 seconds with 4 retries
- Direct curl downloads work fine, but Ansible get_url with checksum validation fails

**Root Cause**:
- Kubespray checksum file (`roles/kubespray_defaults/vars/main/checksums.yml`) contains outdated checksum: `f24ef6afead1443b816fcfc9a6f9fdadb335a3dfab5255a2e2da2cb4fc3b5e30`
- Actual GitHub tarball checksum: `36c50905b9b62a78638bcfb9d1c4faf1efa08e2013265dcd694ec4e370b78dd7`

**Fix Applied**:
Override the incorrect checksum in `kubespray/inventory/homelab/group_vars/all/all.yml`:
```yaml
calico_crds_archive_checksums:
  no_arch:
    3.30.3: sha256:36c50905b9b62a78638bcfb9d1c4faf1efa08e2013265dcd694ec4e370b78dd7
```

**Why This Approach**:
- Overriding in inventory group_vars is the proper way to fix kubespray issues
- Doesn't modify the kubespray installation itself
- Documented in version control
- Will work for future deployments
- Can be easily updated if GitHub tarball changes

**Verification**:
```bash
# Verify actual checksum from GitHub
curl -sL https://github.com/projectcalico/calico/archive/v3.30.3.tar.gz | sha256sum
# Should output: 36c50905b9b62a78638bcfb9d1c4faf1efa08e2013265dcd694ec4e370b78dd7
```

**Date Fixed**: 2025-11-05

---

## Future Considerations

### Potential Upgrades:
- **Cilium CNI**: Migrate to eBPF-based networking for better performance
- **External Etcd**: If scaling beyond 10 control plane nodes
- **Service Mesh**: Add Istio or Linkerd for advanced traffic management
- **GPU Support**: Add GPU node labels and device plugins for ML workloads
- **Cluster Autoscaling**: Implement cluster-autoscaler for dynamic node scaling

### Monitoring and Observability:
- Deploy Prometheus and Grafana via ArgoCD (post-deployment)
- Integrate with existing Elasticsearch cluster for log aggregation
- Add distributed tracing (Jaeger/Tempo) for application debugging

---

## References

- Kubespray Documentation: https://kubespray.io/
- Kubespray GitHub: https://github.com/kubernetes-sigs/kubespray
- Kubernetes Documentation: https://kubernetes.io/docs/
- Calico Documentation: https://docs.tigera.io/calico/latest/about
- Containerd Documentation: https://containerd.io/docs/
- Etcd Documentation: https://etcd.io/docs/

---

## Related Documentation

- Deployment: `docs/KUBESPRAY-DEPLOYMENT.md`
- Operations: `docs/KUBESPRAY-OPERATIONS.md`
- Backup/Restore: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- Troubleshooting: `docs/KUBESPRAY-TROUBLESHOOTING.md`
- Architecture: `docs/KUBESPRAY-ARCHITECTURE.md`

---

*Last Updated: 2025-11-04*
*Maintainer: Homelab Infrastructure Team*
