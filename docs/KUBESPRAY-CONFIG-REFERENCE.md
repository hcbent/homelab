# Kubespray Configuration Reference

Complete reference for all kubespray configuration files, inventory structure, group_vars settings, customization procedures, and testing configuration changes.

## Table of Contents

1. [Inventory Structure](#inventory-structure)
2. [Group Variables](#group-variables)
3. [Host Variables](#host-variables)
4. [Customization Procedures](#customization-procedures)
5. [Testing Configuration Changes](#testing-configuration-changes)

---

## Inventory Structure

### Directory Layout

```
kubespray/inventory/homelab/
├── hosts.ini                        # Main inventory file
├── README.md                        # Inventory documentation
├── group_vars/
│   ├── all/
│   │   ├── all.yml                 # Variables for all hosts
│   │   └── etcd.yml                # Etcd configuration
│   └── k8s_cluster/
│       ├── k8s-cluster.yml         # Main cluster config
│       ├── addons.yml              # Addon selection
│       └── k8s-net-containerd.yml  # Containerd config
└── host_vars/                       # Host-specific overrides
    └── (optional)
```

### hosts.ini

Main inventory file defining cluster topology.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini`

**Format:** INI-style Ansible inventory

**Groups:**
- `[all]`: All nodes in cluster
- `[kube_control_plane]`: Control plane nodes
- `[etcd]`: Etcd member nodes
- `[kube_node]`: Worker nodes
- `[k8s_cluster:children]`: Meta-group combining control plane and workers

**Example:**
```ini
# All hosts
[all]
km01 ansible_host=192.168.10.234
km02 ansible_host=192.168.10.235
km03 ansible_host=192.168.10.236
kube01 ansible_host=192.168.10.237
kube02 ansible_host=192.168.10.238
kube03 ansible_host=192.168.10.239

# Control plane nodes
[kube_control_plane]
km01
km02
km03

# Etcd cluster members
[etcd]
km01
km02
km03

# Worker nodes
[kube_node]
kube01
kube02
kube03

# Kubernetes cluster (meta-group)
[k8s_cluster:children]
kube_control_plane
kube_node

# Common variables for all hosts
[all:vars]
ansible_user=bret
ansible_ssh_private_key_file=/Users/bret/.ssh/github_rsa
ansible_python_interpreter=/usr/bin/python3
```

---

## Group Variables

### all/all.yml

**Purpose:** Variables applied to all nodes in the cluster.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/all/all.yml`

**Key Settings:**

#### Bootstrap OS
```yaml
# Operating system (Ubuntu 25.04)
bootstrap_os: ubuntu
```

#### Ansible Connection
```yaml
# SSH user
ansible_user: bret

# SSH private key
ansible_ssh_private_key_file: /Users/bret/.ssh/github_rsa

# Python interpreter
ansible_python_interpreter: /usr/bin/python3
```

#### DNS Configuration
```yaml
# Upstream DNS servers (homelab gateway)
upstream_dns_servers:
  - 192.168.10.1

# Search domains
searchdomains:
  - lab.thewortmans.org
```

#### Download Configuration
```yaml
# Download binaries once on first node, then distribute
download_run_once: true

# Don't download to localhost (download directly on nodes)
download_localhost: false

# Container images registry
# (can be changed to use mirror/cache)
```

#### Load Balancer
```yaml
# Use localhost nginx as load balancer for API server
loadbalancer_apiserver_localhost: true

# Load balancer type
loadbalancer_apiserver_type: nginx
```

---

### all/etcd.yml

**Purpose:** Etcd-specific configuration.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/all/etcd.yml`

**Key Settings:**

#### Deployment Type
```yaml
# Run etcd as systemd service (not containerized)
etcd_deployment_type: host
```

**Options:**
- `host`: Systemd service (recommended for production)
- `docker`: Dockerized etcd
- `kubeadm`: Managed by kubeadm

#### Data Directory
```yaml
# Etcd data storage location
etcd_data_dir: /var/lib/etcd
```

#### Resource Limits
```yaml
# Memory limit per etcd member
etcd_memory_limit: 2048M

# Maximum database size
etcd_quota_backend_bytes: 2147483648  # 2GB
```

#### Performance Tuning
```yaml
# Snapshot count (default)
etcd_snapshot_count: 10000

# Heartbeat interval
etcd_heartbeat_interval: 250  # ms

# Election timeout
etcd_election_timeout: 5000  # ms
```

---

### k8s_cluster/k8s-cluster.yml

**Purpose:** Main Kubernetes cluster configuration.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml`

**Key Settings:**

#### Kubernetes Version
```yaml
# Kubernetes version to install
kube_version: v1.29.5
```

**To upgrade:** Change this version and run upgrade playbook.

#### Network Plugin
```yaml
# CNI plugin
kube_network_plugin: calico
```

**Options:**
- `calico`: Feature-rich, NetworkPolicy support (default)
- `flannel`: Simple, lightweight
- `cilium`: eBPF-based, advanced features
- `weave`: Legacy option

#### Proxy Configuration
```yaml
# Kube-proxy mode
kube_proxy_mode: iptables

# Strict ARP (required for MetalLB)
kube_proxy_strict_arp: true
```

**Proxy modes:**
- `iptables`: Default, mature
- `ipvs`: Better performance for large clusters
- `ebpf`: Cilium only

#### Cluster Identity
```yaml
# Cluster name
cluster_name: homelab-kubespray

# Service subnet
kube_service_addresses: 10.233.0.0/18

# Pod subnet
kube_pods_subnet: 10.233.64.0/18
```

**Network Planning:**
- Service CIDR: 16,382 service IPs
- Pod CIDR: 16,382 pod IPs
- Per-node prefix: /24 (254 pods per node)

#### DNS Configuration
```yaml
# DNS provider
dns_mode: coredns

# Enable NodeLocal DNS cache
enable_nodelocaldns: true

# NodeLocal DNS IP
nodelocaldns_ip: 169.254.25.10

# DNS domain
cluster_domain: cluster.local
```

#### Container Runtime
```yaml
# Container manager
container_manager: containerd
```

**Options:**
- `containerd`: Recommended (default)
- `crio`: Alternative lightweight runtime
- `docker`: Deprecated

#### Kubelet Configuration
```yaml
# Max pods per node
kubelet_max_pods: 110

# Node status update frequency
node_status_update_frequency: 10s

# Pod eviction hard thresholds
kubelet_eviction_hard:
  memory.available: "256Mi"
  nodefs.available: "10%"
  nodefs.inodesFree: "5%"
  imagefs.available: "10%"
```

#### Feature Gates
```yaml
# Kubernetes feature gates (optional)
kube_feature_gates:
  - GracefulNodeShutdown=true
  - MixedProtocolLBService=true
```

---

### k8s_cluster/addons.yml

**Purpose:** Enable/disable cluster addons.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/addons.yml`

**Key Settings:**

#### Helm
```yaml
# Enable Helm
helm_enabled: true
```

**Required for:** Helm-based application deployments.

#### Metrics Server
```yaml
# Enable metrics-server
metrics_server_enabled: true
```

**Provides:**
- `kubectl top nodes`
- `kubectl top pods`
- Horizontal Pod Autoscaler (HPA)

#### Cert-Manager
```yaml
# Enable cert-manager
cert_manager_enabled: true
```

**Provides:**
- Automatic certificate management
- ClusterIssuer and Issuer resources
- Certificate resource

#### Disabled Addons
```yaml
# MetalLB (deployed via ArgoCD instead)
metallb_enabled: false

# Ingress NGINX (using Traefik instead)
ingress_nginx_enabled: false

# Local path provisioner (using Democratic CSI instead)
local_path_provisioner_enabled: false

# Kubernetes Dashboard (using alternative tools)
dashboard_enabled: false
```

**Rationale:** These components deployed via ArgoCD for GitOps management.

---

### k8s_cluster/k8s-net-containerd.yml

**Purpose:** Containerd-specific configuration.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-net-containerd.yml`

**Key Settings:**

#### Container Runtime
```yaml
# Use containerd
container_manager: containerd
```

#### Storage
```yaml
# Containerd data directory
containerd_storage_dir: /var/lib/containerd
```

#### Limits
```yaml
# Maximum log line size
containerd_max_container_log_line_size: 16384  # 16KB

# GRPC message size
containerd_grpc_max_recv_message_size: 16777216  # 16MB
```

#### OOM Score
```yaml
# OOM score (0 = protected from OOM killer)
containerd_oom_score: 0
```

---

## Host Variables

### Purpose

Host-specific overrides for individual nodes.

**Location:** `/Users/bret/git/homelab/kubespray/inventory/homelab/host_vars/`

**Usage:** Create file named after host (e.g., `km01.yml`).

### Example: Override for Bare Metal Node

**File:** `host_vars/km01.yml`

```yaml
# km01 is bare metal with more resources
# Override kubelet max pods
kubelet_max_pods: 150

# More CPU/memory, can handle more pods
kubelet_eviction_hard:
  memory.available: "1Gi"
  nodefs.available: "10%"
```

### Example: Override for GPU Node

**File:** `host_vars/kube04.yml` (if adding GPU worker)

```yaml
# GPU node specific config
# Label for GPU workloads
node_labels:
  accelerator: nvidia-tesla-gpu
  gpu-type: tesla-t4

# Install NVIDIA container runtime
nvidia_container_runtime_enabled: true
```

---

## Customization Procedures

### Changing Kubernetes Version

**Steps:**

1. **Check kubespray compatibility**:
   - Kubespray supports specific Kubernetes versions
   - Check: https://github.com/kubernetes-sigs/kubespray/releases

2. **Update kubespray**:
   ```bash
   \cd ~/git/kubespray
   git fetch --all
   git checkout release-2.25  # or desired release
   ```

3. **Update cluster config**:
   ```bash
   vi /Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml

   # Change:
   kube_version: v1.30.0
   ```

4. **Run upgrade playbook**:
   ```bash
   \cd /Users/bret/git/homelab/ansible
   ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
     playbooks/upgrade_kubespray_cluster.yml
   ```

---

### Changing CNI Plugin

**WARNING:** Changing CNI on running cluster is complex and risky.

**Recommended:** Deploy new cluster with new CNI.

**If changing CNI:**

1. **Drain all workloads**
2. **Update config**:
   ```yaml
   kube_network_plugin: cilium  # or flannel
   ```

3. **Remove old CNI**:
   ```bash
   kubectl delete -f old-cni-manifests.yaml
   ```

4. **Run cluster playbook** to install new CNI
5. **Verify networking** before un-cordoning nodes

---

### Adding Custom Feature Gates

**Edit:** `k8s_cluster/k8s-cluster.yml`

```yaml
kube_feature_gates:
  - GracefulNodeShutdown=true
  - MixedProtocolLBService=true
  - CustomFeature=true
```

**Apply:**
```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  ~/git/kubespray/cluster.yml
```

---

### Changing Service/Pod CIDR

**WARNING:** Cannot be changed on running cluster. Requires cluster rebuild.

**Steps:**

1. **Update config**:
   ```yaml
   kube_service_addresses: 10.96.0.0/16
   kube_pods_subnet: 10.244.0.0/16
   ```

2. **Backup data** (see KUBESPRAY-BACKUP-RESTORE.md)

3. **Reset cluster**:
   ```bash
   ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
     playbooks/reset_kubespray_cluster.yml
   ```

4. **Redeploy cluster**:
   ```bash
   ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
     playbooks/deploy_kubespray_cluster.yml
   ```

---

### Enabling Etcd Encryption

**Edit:** `all/etcd.yml`

```yaml
# Enable etcd encryption at rest
etcd_enable_encryption: true
etcd_encryption_key: <base64-encoded-key>
```

**Generate key:**
```bash
head -c 32 /dev/urandom | base64
```

**Apply:**
```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  ~/git/kubespray/cluster.yml --tags etcd
```

---

### Customizing Kubelet Settings

**Edit:** `k8s_cluster/k8s-cluster.yml`

```yaml
# Increase max pods
kubelet_max_pods: 150

# Adjust eviction thresholds
kubelet_eviction_hard:
  memory.available: "512Mi"
  nodefs.available: "5%"
  nodefs.inodesFree: "3%"

# Pod eviction timeout
kubelet_eviction_soft_grace_period:
  memory.available: "2m"
  nodefs.available: "2m"
```

**Apply to specific node:**

Create `host_vars/km01.yml`:
```yaml
kubelet_max_pods: 200
```

---

## Testing Configuration Changes

### Test Configuration Syntax

**Ansible syntax check:**
```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  ~/git/kubespray/cluster.yml --syntax-check
```

**Inventory validation:**
```bash
ansible-inventory -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini --list
```

---

### Test with Check Mode (Dry Run)

**Run in check mode:**
```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  ~/git/kubespray/cluster.yml --check --diff
```

**Limitations:**
- Some tasks fail in check mode
- Doesn't catch all issues
- Use for rough validation only

---

### Test on Single Node

**Limit playbook to one node:**
```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  ~/git/kubespray/cluster.yml --limit=kube03
```

**Use case:**
- Test config change on one worker
- Verify before rolling out to all nodes

---

### Test in Staging Environment

**Best practice:** Test changes in staging cluster first.

**Steps:**

1. **Create staging inventory**:
   ```
   kubespray/inventory/staging/
   ```

2. **Clone production config** with changes

3. **Deploy staging cluster**

4. **Test thoroughly**

5. **Apply to production**

---

### Rollback Configuration Changes

**If changes cause issues:**

1. **Revert Git changes**:
   ```bash
   \cd /Users/bret/git/homelab
   git revert HEAD
   git push
   ```

2. **Reapply previous config**:
   ```bash
   ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
     ~/git/kubespray/cluster.yml
   ```

3. **Or restore from backup** (see KUBESPRAY-BACKUP-RESTORE.md)

---

## Configuration Best Practices

### Version Control

**Always commit configuration changes:**
```bash
\cd /Users/bret/git/homelab
git add kubespray/
git commit -m "Update Kubernetes to v1.30.0"
git push
git tag -a config-$(date +%Y%m%d-%H%M%S) -m "Pre-upgrade checkpoint"
git push --tags
```

### Documentation

**Document custom changes:**
- Add comments to YAML files
- Update `kubespray/CONFIG-DECISIONS.md`
- Note rationale for non-standard configs

### Testing

**Always test before production:**
1. Syntax check
2. Check mode dry run
3. Single node test (if possible)
4. Staging environment (if available)
5. Backup before applying

### Incremental Changes

**Make small, incremental changes:**
- Change one setting at a time
- Test each change
- Easier to identify issues
- Easier to rollback

### Monitoring

**Monitor cluster after changes:**
```bash
# Watch nodes
watch kubectl get nodes

# Watch pods
watch kubectl get pods -A

# Check logs
kubectl logs -n kube-system <pod> -f

# Check etcd
ssh bret@km01
sudo ETCDCTL_API=3 etcdctl endpoint health ...
```

---

## Related Documentation

- **Deployment**: `docs/KUBESPRAY-DEPLOYMENT.md`
- **Operations**: `docs/KUBESPRAY-OPERATIONS.md`
- **Backup/Restore**: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Troubleshooting**: `docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Architecture**: `docs/KUBESPRAY-ARCHITECTURE.md`
- **Config Decisions**: `kubespray/CONFIG-DECISIONS.md`

---

*Last Updated: 2025-11-04*
