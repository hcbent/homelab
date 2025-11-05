# Kubespray Kubernetes Cluster Configuration

This directory contains the kubespray configuration for your homelab Kubernetes cluster.

## Quick Deploy

**The fastest path to deployment:**

See [QUICK-DEPLOY.md](QUICK-DEPLOY.md) for step-by-step instructions.

## Directory Structure

```
kubespray/
├── inventory/
│   └── homelab/
│       ├── hosts.ini              # Inventory with all 6 nodes
│       ├── group_vars/
│       │   ├── all/
│       │   │   ├── all.yml        # Common variables
│       │   │   └── etcd.yml       # Etcd configuration
│       │   └── k8s_cluster/
│       │       ├── k8s-cluster.yml           # Main cluster config
│       │       ├── addons.yml                # Addon configuration
│       │       └── k8s-net-containerd.yml    # Containerd config
│       └── README.md              # Inventory documentation
├── CONFIG-DECISIONS.md            # Configuration rationale
├── DEPLOYMENT-PROCEDURES.md       # Complete deployment guide
└── QUICK-DEPLOY.md               # Fast deployment reference
```

## Cluster Architecture

- **Control Plane Nodes:** km01 (bare metal), km02-km03 (VMs)
- **Worker Nodes:** kube01-kube03 (VMs)
- **Etcd:** Distributed across all 3 control plane nodes for HA
- **CNI:** Calico (novice-friendly)
- **Container Runtime:** containerd
- **DNS:** CoreDNS with NodeLocal DNS cache

## How to Deploy

### Prerequisites

Run pre-flight checks:

```bash
cd /Users/bret/git/homelab/ansible
ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/kubespray_preflight.yml
```

### Deployment Command

**IMPORTANT:** Run kubespray from its own directory (not from the wrapper playbook):

```bash
cd ~/git/kubespray
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini cluster.yml
```

**Why?** Kubespray uses relative paths for roles. Running from kubespray's directory ensures proper role resolution.

### Post-Deployment

After deployment, see platform component deployment:

- Storage: `/Users/bret/git/homelab/k8s/democratic-csi/README.md`
- MetalLB: `/Users/bret/git/homelab/k8s/metallb/README.md`
- Traefik: `/Users/bret/git/homelab/k8s/traefik/README.md`
- ArgoCD: `/Users/bret/git/homelab/k8s/argocd/README.md`

## Operations

Common operational tasks:

### Add Nodes

```bash
cd ~/git/kubespray
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini scale.yml
```

### Upgrade Cluster

```bash
cd ~/git/kubespray
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini upgrade-cluster.yml
```

### Reset Cluster (DESTRUCTIVE)

```bash
cd ~/git/kubespray
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini reset.yml
```

## Documentation

- **Quick Start:** [QUICK-DEPLOY.md](QUICK-DEPLOY.md)
- **Complete Deployment Guide:** [DEPLOYMENT-PROCEDURES.md](DEPLOYMENT-PROCEDURES.md)
- **Operations:** `/Users/bret/git/homelab/docs/KUBESPRAY-OPERATIONS.md`
- **Backup/Restore:** `/Users/bret/git/homelab/docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Troubleshooting:** `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Architecture:** `/Users/bret/git/homelab/docs/KUBESPRAY-ARCHITECTURE.md`
- **Configuration Reference:** `/Users/bret/git/homelab/docs/KUBESPRAY-CONFIG-REFERENCE.md`

## Network Configuration

- **Node Network:** 192.168.10.234-239
- **Pod Network:** 10.233.64.0/18
- **Service Network:** 10.233.0.0/18
- **MetalLB Pool:** 192.168.100.0/24
- **Gateway:** 192.168.10.1
- **DNS:** 192.168.10.1
- **Domain:** lab.thewortmans.org

## Support

For issues or questions:
1. Check [KUBESPRAY-TROUBLESHOOTING.md](/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md)
2. Review kubespray logs on control plane nodes
3. Check [Kubespray documentation](https://kubespray.io)
