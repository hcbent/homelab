# Kubespray Homelab Inventory

This directory contains the Kubespray inventory configuration for the homelab Kubernetes cluster.

## Cluster Architecture

### Control Plane Nodes (3 nodes)

The control plane runs Kubernetes management components and provides high availability through distributed etcd.

| Hostname | IP Address | Type | Specs | Location | Role |
|----------|------------|------|-------|----------|------|
| km01 | 192.168.10.234 | Bare Metal | 4 cores, 16GB RAM, 1TB storage | Physical hardware | Control Plane + etcd |
| km02 | 192.168.10.235 | VM | 4 cores, 8GB RAM, 100GB disk | Proxmox pve1 | Control Plane + etcd |
| km03 | 192.168.10.236 | VM | 4 cores, 8GB RAM, 100GB disk | Proxmox pve2 | Control Plane + etcd |

**Control Plane Components:**
- **kube-apiserver**: Exposes the Kubernetes API
- **kube-scheduler**: Schedules pods to nodes
- **kube-controller-manager**: Runs controller processes
- **etcd**: Distributed key-value store for cluster state

### Worker Nodes (3 nodes)

Worker nodes run application workloads and are sized for general-purpose computing.

| Hostname | IP Address | Type | Specs | Location | Role |
|----------|------------|------|-------|----------|------|
| kube01 | 192.168.10.237 | VM | 8 cores, 16GB RAM, 200GB disk | Proxmox pve3 | Worker |
| kube02 | 192.168.10.238 | VM | 8 cores, 16GB RAM, 200GB disk | Proxmox pve1 | Worker |
| kube03 | 192.168.10.239 | VM | 8 cores, 16GB RAM, 200GB disk | Proxmox pve2 | Worker |

**Worker Components:**
- **kubelet**: Manages pods on the node
- **kube-proxy**: Network proxy for service networking
- **Container runtime**: Containerd for running containers

## Etcd Distribution Strategy

This cluster uses **stacked etcd topology**, where etcd runs on the same nodes as the Kubernetes control plane. This is the recommended approach for smaller clusters and simplifies management.

### Why Stacked Etcd?

**Advantages:**
- Simpler deployment and management (fewer nodes to maintain)
- Lower resource requirements (no dedicated etcd nodes)
- Suitable for homelab and small production environments
- Built-in high availability with 3 etcd members

**Quorum Requirements:**
- 3 etcd members provide quorum with 1 node failure tolerance
- Minimum 2 nodes must be online for cluster operations
- Majority (2 out of 3) required for etcd writes

### Etcd Member Names

Each control plane node has a unique etcd member name:
- **km01**: `etcd1` (primary, bare metal for stability)
- **km02**: `etcd2` (VM on pve1)
- **km03**: `etcd3` (VM on pve2)

## Network Configuration

### Addressing

- **Node Network**: 192.168.10.0/24
  - Control plane: 192.168.10.234-236
  - Workers: 192.168.10.237-239
- **Pod Network**: 10.233.64.0/18 (Calico CNI)
- **Service Network**: 10.233.0.0/18
- **MetalLB Pool**: 192.168.100.0/24 (for LoadBalancer services)

### DNS and Gateway

- **Gateway**: 192.168.10.1
- **DNS**: 192.168.10.1 (Pi-hole)
- **Domain**: lab.thewortmans.org
- **Cluster DNS**: CoreDNS (internal cluster DNS)

## Inventory Structure

### File Organization

```
kubespray/inventory/homelab/
├── hosts.ini                    # Main inventory file (node definitions)
├── group_vars/                  # Group-level variables
│   ├── all/                     # Variables for all nodes
│   │   └── all.yml              # Common settings
│   └── k8s_cluster/             # Variables for k8s_cluster group
│       ├── k8s-cluster.yml      # Core Kubernetes settings
│       ├── addons.yml           # Optional addons configuration
│       └── k8s-net-containerd.yml  # Container runtime settings
├── host_vars/                   # Host-specific variables (if needed)
└── README.md                    # This file
```

### Inventory Groups

The `hosts.ini` file defines the following Ansible groups:

- **`all`**: All nodes in the inventory
- **`kube_control_plane`**: Control plane nodes (km01, km02, km03)
- **`etcd`**: Etcd cluster members (inherited from kube_control_plane)
- **`kube_node`**: Worker nodes (kube01, kube02, kube03)
- **`k8s_cluster`**: All Kubernetes nodes (control plane + workers)

## Adding New Nodes

### Adding a Worker Node

1. **Provision the VM** (if VM):
   ```bash
   cd /Users/bret/git/homelab/tf/kubespray/
   # Edit main.tf to add new worker node
   terraform apply -var-file=terraform.tfvars
   ```

2. **Add to inventory**:
   Edit `hosts.ini` and add the new node to the `[kube_node]` section:
   ```ini
   [kube_node]
   kube01 ansible_host=192.168.10.237
   kube02 ansible_host=192.168.10.238
   kube03 ansible_host=192.168.10.239
   kube04 ansible_host=192.168.10.240  # New worker
   ```

3. **Run the scale playbook**:
   ```bash
   cd /Users/bret/git/homelab/ansible/
   ansible-playbook add_kubespray_node.yml
   ```

4. **Verify the node joined**:
   ```bash
   kubectl get nodes
   kubectl label node kube04 node-role.kubernetes.io/worker=""
   ```

### Adding a Control Plane Node

**⚠️ CAUTION:** Adding control plane nodes is more complex and affects etcd quorum.

1. **Consider odd numbers**: Etcd requires an odd number of members for optimal quorum (3, 5, 7, etc.)

2. **Provision the VM** (if VM):
   ```bash
   cd /Users/bret/git/homelab/tf/kubespray/
   # Edit main.tf to add new control plane node
   terraform apply -var-file=terraform.tfvars
   ```

3. **Add to inventory**:
   Edit `hosts.ini` and add to both `[kube_control_plane]` and `[etcd]` (via inheritance):
   ```ini
   [kube_control_plane]
   km01 ansible_host=192.168.10.234 etcd_member_name=etcd1
   km02 ansible_host=192.168.10.235 etcd_member_name=etcd2
   km03 ansible_host=192.168.10.236 etcd_member_name=etcd3
   km04 ansible_host=192.168.10.240 etcd_member_name=etcd4  # New control plane
   ```

4. **Run the scale playbook**:
   ```bash
   cd /Users/bret/git/homelab/ansible/
   ansible-playbook add_kubespray_node.yml
   ```

5. **Verify etcd quorum**:
   ```bash
   # SSH to any control plane node
   ssh bret@192.168.10.234

   # Check etcd member list
   sudo ETCDCTL_API=3 etcdctl \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/ssl/etcd/ssl/ca.pem \
     --cert=/etc/ssl/etcd/ssl/node-km01.pem \
     --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
     member list

   # Check etcd cluster health
   sudo ETCDCTL_API=3 etcdctl \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/ssl/etcd/ssl/ca.pem \
     --cert=/etc/ssl/etcd/ssl/node-km01.pem \
     --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
     endpoint health
   ```

## Removing Nodes

### Removing a Worker Node

1. **Drain the node**:
   ```bash
   kubectl drain kube04 --ignore-daemonsets --delete-emptydir-data
   ```

2. **Delete from cluster**:
   ```bash
   kubectl delete node kube04
   ```

3. **Remove from inventory**:
   Edit `hosts.ini` and remove the node from `[kube_node]` section

4. **Destroy the VM** (if VM):
   ```bash
   cd /Users/bret/git/homelab/tf/kubespray/
   terraform destroy -target=proxmox_vm_qemu.kube04
   ```

### Removing a Control Plane Node

**⚠️ CRITICAL:** Removing control plane nodes affects etcd quorum and cluster availability.

**Before removal:**
- Ensure cluster has at least 3 control plane nodes
- Never remove multiple control plane nodes simultaneously
- Backup etcd before making changes

1. **Remove etcd member first**:
   ```bash
   # SSH to any control plane node
   ssh bret@192.168.10.234

   # List etcd members to get member ID
   sudo ETCDCTL_API=3 etcdctl \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/ssl/etcd/ssl/ca.pem \
     --cert=/etc/ssl/etcd/ssl/node-km01.pem \
     --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
     member list

   # Remove etcd member (replace MEMBER_ID with actual ID)
   sudo ETCDCTL_API=3 etcdctl \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/ssl/etcd/ssl/ca.pem \
     --cert=/etc/ssl/etcd/ssl/node-km01.pem \
     --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
     member remove MEMBER_ID
   ```

2. **Drain and delete the node**:
   ```bash
   kubectl drain km04 --ignore-daemonsets --delete-emptydir-data
   kubectl delete node km04
   ```

3. **Remove from inventory**: Edit `hosts.ini`

4. **Destroy the VM** (if VM)

## SSH Access

All nodes use SSH key authentication with the following configuration:

- **User**: `bret`
- **SSH Key**: `/Users/bret/.ssh/github_rsa`
- **Python Interpreter**: `/usr/bin/python3`

### Testing SSH Access

Test connectivity to all nodes:

```bash
# Control plane nodes
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234  # km01
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.235  # km02
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.236  # km03

# Worker nodes
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.237  # kube01
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.238  # kube02
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.239  # kube03
```

### Using Ansible to Test

```bash
# Test all nodes
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini all -m ping

# Test control plane only
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini kube_control_plane -m ping

# Test workers only
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini kube_node -m ping
```

## Verification Commands

### Check Cluster Status

```bash
# Get all nodes with roles
kubectl get nodes -o wide

# Check node labels
kubectl get nodes --show-labels

# Check control plane pods
kubectl get pods -n kube-system -o wide
```

### Check Etcd Health

```bash
# SSH to km01 (or any control plane node)
ssh bret@192.168.10.234

# Check etcd health
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health

# Check etcd member list
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list -w table
```

## Troubleshooting

### Node Not Joining Cluster

1. **Check SSH connectivity**:
   ```bash
   ansible -i hosts.ini <node> -m ping
   ```

2. **Check Python installation**:
   ```bash
   ansible -i hosts.ini <node> -m shell -a "python3 --version"
   ```

3. **Check sudo access**:
   ```bash
   ansible -i hosts.ini <node> -m shell -a "sudo -l" -b
   ```

### Etcd Quorum Issues

1. **Check member status**:
   ```bash
   sudo ETCDCTL_API=3 etcdctl member list
   ```

2. **Verify etcd certificates**:
   ```bash
   ls -la /etc/ssl/etcd/ssl/
   ```

3. **Check etcd logs**:
   ```bash
   sudo journalctl -u etcd -f
   ```

## Related Documentation

- **Deployment Guide**: `/Users/bret/git/homelab/docs/KUBESPRAY-DEPLOYMENT.md`
- **Operations Guide**: `/Users/bret/git/homelab/docs/KUBESPRAY-OPERATIONS.md`
- **Troubleshooting**: `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Kubespray Official Docs**: https://kubespray.io/

## Network Diagram

```
                        Internet
                            |
                    [192.168.10.1]
                      Gateway/DNS
                            |
          +-----------------+------------------+
          |                 |                  |
    [Control Plane]    [Control Plane]   [Control Plane]
       km01 (.234)        km02 (.235)       km03 (.236)
    Bare Metal, 16GB    VM pve1, 8GB      VM pve2, 8GB
         etcd1              etcd2             etcd3
          |                 |                  |
          +--------+--------+--------+---------+
                   |                 |
          +--------+--------+--------+--------+
          |                 |                 |
      [Worker]          [Worker]          [Worker]
    kube01 (.237)     kube02 (.238)     kube03 (.239)
    VM pve3, 16GB     VM pve1, 16GB     VM pve2, 16GB
          |                 |                 |
          +-----------------+-----------------+
                            |
                      [Applications]
                   Pods, Services, Ingress
                            |
                      [MetalLB Pool]
                   192.168.100.0/24
                            |
                    [External Access]
              via Traefik Ingress + NPM
```

## Notes

- **km01** is bare metal hardware, NOT provisioned by Terraform
- **km02, km03, kube01, kube02, kube03** are VMs managed by Terraform
- All VMs use Ubuntu 25.04 operating system
- VMs are distributed across 3 Proxmox nodes (pve1, pve2, pve3) for HA
- Storage backend: FreeNAS "tank" pool via Democratic CSI
- Network: 192.168.10.0/24 with vmbr0 bridge
- CNI: Calico for pod networking
- Container Runtime: Containerd

## Maintenance Windows

When performing maintenance that affects control plane nodes:

1. **Never reboot multiple control plane nodes simultaneously**
2. **Always maintain etcd quorum** (minimum 2 of 3 nodes online)
3. **Backup etcd before major changes**
4. **Test changes on worker nodes first when possible**

## Support

For questions or issues related to this cluster:

1. Check troubleshooting documentation
2. Review kubespray logs: `~/git/kubespray/ansible.log`
3. Check cluster logs: `kubectl logs` and `journalctl`
4. Consult Kubespray documentation: https://kubespray.io/
