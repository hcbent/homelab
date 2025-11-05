# Kubespray Cluster Architecture Documentation

Comprehensive architecture documentation for the kubespray Kubernetes cluster including cluster design, component inventory, security model, high availability, and scalability considerations.

## Table of Contents

1. [Cluster Design](#cluster-design)
2. [Component Inventory](#component-inventory)
3. [Security Model](#security-model)
4. [High Availability](#high-availability)
5. [Scalability](#scalability)

---

## Cluster Design

### Overview

The kubespray cluster is a production-grade Kubernetes deployment designed for homelab use with enterprise-level reliability and features.

**Cluster Specifications:**
- **Name**: homelab-kubespray
- **Kubernetes Version**: v1.29.5
- **Total Nodes**: 6 (3 control plane + 3 workers)
- **High Availability**: 3-member etcd cluster, multiple control plane nodes
- **Container Runtime**: containerd
- **CNI**: Calico

### Node Topology

#### Control Plane Nodes

**Purpose:** Run Kubernetes control plane components and etcd.

| Node  | Type       | IP             | Specs                    | Location |
|-------|------------|----------------|--------------------------|----------|
| km01  | Bare Metal | 192.168.10.234 | 4 cores, 16GB RAM, 1TB   | Physical |
| km02  | VM (pve1)  | 192.168.10.235 | 4 cores, 8GB RAM, 100GB  | Proxmox  |
| km03  | VM (pve2)  | 192.168.10.236 | 4 cores, 8GB RAM, 100GB  | Proxmox  |

**Components Running:**
- kube-apiserver
- kube-scheduler
- kube-controller-manager
- etcd
- kubelet
- kube-proxy
- Calico node agent
- CoreDNS
- NodeLocal DNS cache

**Taints:** Control plane nodes are tainted to prevent workload scheduling (standard Kubernetes behavior).

#### Worker Nodes

**Purpose:** Run application workloads.

| Node   | Type       | IP             | Specs                     | Location     |
|--------|------------|----------------|---------------------------|--------------|
| kube01 | VM (pve3)  | 192.168.10.237 | 8 cores, 16GB RAM, 200GB  | Proxmox pve3 |
| kube02 | VM (pve1)  | 192.168.10.238 | 8 cores, 16GB RAM, 200GB  | Proxmox pve1 |
| kube03 | VM (pve2)  | 192.168.10.239 | 8 cores, 16GB RAM, 200GB  | Proxmox pve2 |

**Components Running:**
- kubelet
- kube-proxy
- Calico node agent
- NodeLocal DNS cache
- Democratic CSI node driver
- Application pods

**Distribution:** Workers distributed across Proxmox nodes (pve1, pve2, pve3) for infrastructure-level redundancy.

### Network Topology

```
                                    Internet
                                       |
                                    Gateway
                                  192.168.10.1
                                       |
                        +--------------+---------------+
                        |                              |
                  Physical Network              MetalLB Pool
                  192.168.10.0/24              192.168.100.0/24
                        |
        +---------------+----------------+
        |               |                |
   Control Plane    Workers         Services/Ingress
   km01-km03      kube01-03         LoadBalancer IPs
        |               |                |
        +---------------+----------------+
                        |
                   Calico CNI
                        |
        +---------------+----------------+
        |                                |
   Service Network                  Pod Network
   10.233.0.0/18                   10.233.64.0/18
```

**Network Segments:**

1. **Physical Network** (192.168.10.0/24):
   - Node-to-node communication
   - API server access
   - Etcd cluster communication
   - Gateway: 192.168.10.1
   - DNS: 192.168.10.1

2. **Service Network** (10.233.0.0/18):
   - Kubernetes ClusterIP services
   - Virtual IPs managed by kube-proxy
   - ~16,382 service IPs available

3. **Pod Network** (10.233.64.0/18):
   - Pod-to-pod communication
   - Managed by Calico CNI
   - ~16,382 pod IPs available
   - Per-node allocation: /24 (254 pods per node)

4. **MetalLB Pool** (192.168.100.0/24):
   - LoadBalancer service external IPs
   - Layer 2 mode (ARP-based)
   - ~254 LoadBalancer IPs available

### Storage Architecture

```
                    Kubernetes Cluster
                           |
                   Democratic CSI
                           |
        +------------------+------------------+
        |                                     |
   iSCSI Driver                          NFS Driver
   (Block Storage)                    (Shared Storage)
        |                                     |
        +------------------+------------------+
                           |
                    FreeNAS/TrueNAS
                     tank/k8s/*
                           |
                    ZFS Storage Pool
```

**Storage Components:**

1. **Democratic CSI**:
   - Two drivers: iSCSI (block) and NFS (shared)
   - Dynamic provisioning
   - ZFS snapshot support

2. **Storage Classes**:
   - `freenas-iscsi-csi` (default): RWO volumes
   - `freenas-nfs-csi`: RWX volumes

3. **FreeNAS Datasets**:
   - `tank/k8s/volumes`: iSCSI volumes
   - `tank/k8s/snapshots`: iSCSI snapshots
   - `tank/k8s/nfs`: NFS volumes
   - `tank/k8s/nfs-snapshots`: NFS snapshots

---

## Component Inventory

### Control Plane Components

#### Kubernetes API Server

**Purpose:** Frontend for Kubernetes control plane.

**Details:**
- **Version**: v1.29.5
- **Port**: 6443
- **Replicas**: 3 (one per control plane node)
- **Load Balancing**: Local nginx proxy on each node
- **Authentication**: x509 client certificates, service account tokens
- **Authorization**: RBAC

**High Availability:**
- Each control plane node runs kube-apiserver
- Clients connect to local nginx proxy (127.0.0.1:6443)
- Nginx proxies to all 3 API servers
- Survives loss of 2 control plane nodes

#### Etcd

**Purpose:** Distributed key-value store for cluster state.

**Details:**
- **Version**: v3.5.x
- **Deployment**: Host-based (systemd service)
- **Data Directory**: /var/lib/etcd
- **Ports**: 2379 (client), 2380 (peer)
- **Members**: 3 (km01, km02, km03)
- **Quorum**: Majority (2 of 3)
- **Memory Limit**: 2GB per member
- **Database Quota**: 2GB

**Configuration:**
```yaml
etcd_deployment_type: host
etcd_data_dir: /var/lib/etcd
etcd_memory_limit: 2048M
etcd_quota_backend_bytes: 2147483648
```

#### Kube-Scheduler

**Purpose:** Assigns pods to nodes based on resource requirements and constraints.

**Details:**
- **Version**: v1.29.5
- **Replicas**: 3 (one per control plane node, leader election)
- **Port**: 10259

#### Kube-Controller-Manager

**Purpose:** Runs controller processes (replication, endpoints, namespace, service account).

**Details:**
- **Version**: v1.29.5
- **Replicas**: 3 (one per control plane node, leader election)
- **Port**: 10257

### Node Components

#### Kubelet

**Purpose:** Node agent that runs pods.

**Details:**
- **Version**: v1.29.5
- **Runs On**: All nodes (control plane + workers)
- **Container Runtime**: containerd via CRI
- **Configuration**: /var/lib/kubelet/config.yaml

#### Kube-Proxy

**Purpose:** Network proxy implementing Kubernetes Service concept.

**Details:**
- **Version**: v1.29.5
- **Mode**: iptables
- **Runs On**: All nodes
- **Strict ARP**: Enabled (required for MetalLB)

**Configuration:**
```yaml
kube_proxy_mode: iptables
kube_proxy_strict_arp: true
```

#### Containerd

**Purpose:** Container runtime.

**Details:**
- **Version**: Latest stable
- **Socket**: /run/containerd/containerd.sock
- **Storage**: /var/lib/containerd
- **Runtime**: runc (OCI)

**Configuration:**
```yaml
container_manager: containerd
containerd_storage_dir: /var/lib/containerd
containerd_max_container_log_line_size: 16384
containerd_grpc_max_recv_message_size: 16777216
```

### Network Components

#### Calico CNI

**Purpose:** Container networking and network policy.

**Details:**
- **Version**: Latest stable from kubespray
- **Mode**: IPIP (can be changed to VXLAN or native routing)
- **IPAM**: Calico IPAM
- **Dataplane**: iptables (can be upgraded to eBPF)
- **Pod CIDR**: 10.233.64.0/18
- **Node Prefix**: /24

**Components:**
- **calico-node**: DaemonSet on all nodes
- **calico-kube-controllers**: Deployment (1 replica)
- **calico-apiserver**: Deployment (optional)

#### CoreDNS

**Purpose:** Cluster DNS service.

**Details:**
- **Replicas**: 2 (for HA)
- **Service IP**: 10.233.0.3 (first IP in service network)
- **Port**: 53 (UDP/TCP)
- **Upstream DNS**: 192.168.10.1 (homelab gateway)

**Configuration:**
```yaml
dns_mode: coredns
kube_service_addresses: 10.233.0.0/18
cluster_name: homelab-kubespray
```

#### NodeLocal DNS Cache

**Purpose:** Caches DNS queries on each node for performance.

**Details:**
- **Deployment**: DaemonSet on all nodes
- **Local IP**: 169.254.25.10 (link-local)
- **Upstream**: CoreDNS (10.233.0.3)

**Benefits:**
- Reduced DNS query latency
- Lower load on CoreDNS
- Better DNS availability

### Storage Components

#### Democratic CSI

**Purpose:** Dynamic persistent volume provisioning.

**Details:**
- **Controller**: Deployment (1 replica) on workers
- **Node Driver**: DaemonSet on all worker nodes
- **Protocols**: iSCSI and NFS
- **Backend**: FreeNAS/TrueNAS

**Storage Classes:**
```yaml
freenas-iscsi-csi:
  provisioner: org.democratic-csi.iscsi
  reclaimPolicy: Delete
  volumeBindingMode: Immediate
  allowVolumeExpansion: true

freenas-nfs-csi:
  provisioner: org.democratic-csi.nfs
  reclaimPolicy: Delete
  volumeBindingMode: Immediate
  allowVolumeExpansion: true
```

### Platform Components

#### MetalLB

**Purpose:** LoadBalancer implementation for bare metal.

**Details:**
- **Mode**: Layer 2 (ARP-based)
- **IP Pool**: 192.168.100.0/24
- **Components**:
  - **controller**: Deployment (1 replica)
  - **speaker**: DaemonSet on all nodes

#### Traefik

**Purpose:** Ingress controller.

**Details:**
- **Replicas**: 2 (for HA)
- **Service Type**: LoadBalancer (gets IP from MetalLB)
- **Ports**:
  - HTTP: 80
  - HTTPS: 443
  - Dashboard: 9000
- **Features**:
  - Automatic TLS with cert-manager
  - Middleware support
  - IngressRoute CRD support

#### Cert-Manager

**Purpose:** Automated certificate management.

**Details:**
- **Installed By**: Kubespray
- **Components**:
  - cert-manager
  - cert-manager-cainjector
  - cert-manager-webhook
- **Issuers**:
  - selfsigned-cluster-issuer (bootstrap)
  - ca-cluster-issuer (internal CA)

#### ArgoCD

**Purpose:** GitOps continuous delivery.

**Details:**
- **Components**:
  - argocd-server (UI/API)
  - argocd-application-controller
  - argocd-repo-server
  - argocd-redis
  - argocd-dex-server (SSO)
- **Repository**: Points to homelab Git repo
- **Sync Policy**: Manual (can be automated)

---

## Security Model

### Authentication Mechanisms

#### User Authentication

1. **x509 Client Certificates**:
   - Admin kubeconfig uses client certificates
   - Certificates in `/etc/kubernetes/pki`
   - Auto-rotation by kubelet

2. **Service Account Tokens**:
   - JWT tokens for pod authentication
   - Projected service account tokens (TTL: 1 hour)

3. **OIDC** (optional):
   - Can integrate with external identity provider
   - Not configured by default

### Authorization (RBAC)

**Role-Based Access Control** enabled by default.

**Key Roles:**
- `cluster-admin`: Full cluster access
- `admin`: Namespace admin
- `edit`: Edit resources
- `view`: Read-only

**Service Accounts:**
- Each namespace has default service account
- Custom service accounts for applications
- Least-privilege principle

### Network Policies

**Calico supports Kubernetes NetworkPolicies:**
- Namespace isolation
- Pod-to-pod traffic control
- Ingress/egress rules

**Not configured by default** - must be created per application.

### Secret Management

**HashiCorp Vault Integration:**
- Infrastructure secrets stored in Vault
- Vault address: https://192.168.10.101:8200
- Secret paths:
  - `secret/homelab/proxmox/terraform`
  - `secret/homelab/freenas/credentials`
  - `secret/homelab/freenas/ssh`

**Kubernetes Secrets:**
- Base64 encoded (not encrypted at rest)
- Can enable encryption at rest with encryption provider
- External Secrets Operator (ESO) can sync from Vault

### Certificate Management

**Internal Certificates:**
- **Cluster CA**: Self-signed root CA
- **Component Certificates**: Signed by cluster CA
- **Auto-Rotation**: Kubelet rotates certificates
- **Cert-Manager**: Issues application certificates

**External Certificates:**
- NGINX Proxy Manager handles Let's Encrypt
- Cluster doesn't manage public-facing certificates

### Pod Security

**Pod Security Standards** (PSS):
- **Privileged**: No restrictions
- **Baseline**: Minimal restrictions
- **Restricted**: Heavily restricted

**Not enforced cluster-wide** - can be enabled per namespace.

### API Server Security

**TLS Only:**
- All communication encrypted
- Port 6443 (HTTPS)
- No insecure port

**Audit Logging:**
- Can be enabled for compliance
- Logs all API requests

---

## High Availability

### Etcd High Availability

**3-Member Cluster:**
- **Quorum**: 2 of 3 members required
- **Fault Tolerance**: Can lose 1 member
- **Recommendation**: 5 members for better HA (tolerates 2 failures)

**Failure Scenarios:**
- 1 member down: Cluster operational (2/3 quorum)
- 2 members down: Cluster read-only (no quorum)
- 3 members down: Complete failure (restore from backup)

**Best Practices:**
- Regular etcd backups (automated daily)
- Monitor etcd health
- Fast member replacement
- Consider 5-member cluster for critical workloads

### Control Plane Redundancy

**3 Control Plane Nodes:**
- **API Server**: 3 replicas, nginx load balancing
- **Scheduler**: 3 replicas, leader election
- **Controller-Manager**: 3 replicas, leader election

**API Server HA:**
```
Client (kubectl)
    |
    v
Local nginx proxy (127.0.0.1:6443)
    |
    +---> km01 API server (192.168.10.234:6443)
    +---> km02 API server (192.168.10.235:6443)
    +---> km03 API server (192.168.10.236:6443)
```

**Failure Scenarios:**
- 1 control plane down: Cluster fully operational
- 2 control planes down: Cluster operational if 1 API server + etcd quorum
- 3 control planes down: Complete outage

### Worker Node Redundancy

**3 Worker Nodes:**
- Application pods distributed via anti-affinity
- Workloads should have replicas >= 2
- Pod disruption budgets (PDB) for critical apps

**Failure Scenarios:**
- 1 worker down: Pods rescheduled to remaining workers
- 2 workers down: May have resource pressure
- 3 workers down: All workloads down

**Recommendations:**
- Set pod anti-affinity for HA apps
- Use PodDisruptionBudgets
- Monitor resource usage
- Add more workers as needed

### Load Balancing Strategies

**Internal Load Balancing:**
- **API Server**: Local nginx proxy on each node
- **CoreDNS**: Kubernetes service load balances to 2 replicas
- **Kube-Proxy**: iptables rules for service load balancing

**External Load Balancing:**
- **MetalLB**: Layer 2 mode for LoadBalancer services
- **Traefik**: Distributes ingress traffic to pods

### Backup and Recovery

**Regular Backups:**
- Etcd: Daily automated snapshots
- Configuration: Git repository
- Terraform state: After every change
- Application state: Per-application strategy

**Recovery Time Objectives (RTO):**
- Single node failure: Minutes (automatic)
- Control plane failure: 30-60 minutes (manual intervention)
- Complete cluster failure: 2-4 hours (full rebuild + restore)

---

## Scalability

### Current Capacity

**Cluster Limits:**
- **Nodes**: 6 (3 control plane + 3 workers)
- **Pods**: ~750 (254 per worker node × 3)
- **Services**: ~16,382 (service CIDR size)
- **Storage**: Limited by FreeNAS capacity

**Resource Totals:**
- **CPU**: 24 cores (workers), 12 cores (control plane)
- **Memory**: 48GB (workers), 32GB (control plane)
- **Storage**: 600GB (workers), 200GB (control plane)

### Horizontal Scaling (Add Nodes)

**Adding Workers:**
- Can add unlimited worker nodes
- Each worker adds 254 pod capacity
- Follow procedure in `KUBESPRAY-OPERATIONS.md`

**Adding Control Plane:**
- Recommended odd numbers (3, 5, 7)
- 5 members: Tolerates 2 failures
- 7 members: Tolerates 3 failures (overkill for homelab)
- Diminishing returns beyond 5

**Limitations:**
- Etcd performance degrades with too many members
- More control plane = more overhead
- Network bandwidth

### Vertical Scaling (Increase Resources)

**VM Resources:**
- Can increase CPU/memory via Terraform
- Requires VM shutdown
- Update `tf/kubespray/main.tf`

**Bare Metal (km01):**
- Fixed resources
- Cannot scale without hardware upgrade

### Resource Limits and Quotas

**ResourceQuotas** (per namespace):
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
```

**LimitRanges** (per pod/container):
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: cpu-mem-limit-range
spec:
  limits:
  - max:
      cpu: "4"
      memory: 8Gi
    min:
      cpu: "100m"
      memory: 64Mi
    type: Container
```

### Future Expansion Considerations

**Short-Term (Next 6 months):**
- Add 2 more workers (kube04-05) for more capacity
- Consider 5th control plane node (km04) for better HA

**Medium-Term (6-12 months):**
- Separate GPU node for ML workloads
- Dedicated monitoring node
- Expand storage capacity

**Long-Term (1+ years):**
- Multi-cluster setup (separate clusters per environment)
- Service mesh (Istio/Linkerd) for advanced networking
- Upgrade CNI to Cilium for eBPF features

**Scalability Metrics to Monitor:**
- Pod count approaching limit
- Node CPU/memory >80%
- Storage pool utilization >70%
- Etcd database size >1.5GB

---

## Related Documentation

- **Deployment**: `docs/KUBESPRAY-DEPLOYMENT.md`
- **Operations**: `docs/KUBESPRAY-OPERATIONS.md`
- **Backup/Restore**: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Troubleshooting**: `docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Configuration**: `docs/KUBESPRAY-CONFIG-REFERENCE.md`
- **Config Decisions**: `kubespray/CONFIG-DECISIONS.md`

---

*Last Updated: 2025-11-04*
