# Homelab Documentation Index

Comprehensive index of all homelab infrastructure documentation organized by category and deployment method.

## Quick Start Guides

Fast-track guides for common deployment scenarios:

- **[Kubespray Quick Start](KUBESPRAY-QUICKSTART.md)** - Fast deployment reference for production Kubernetes
- **[K3s Deployment Guide](DEPLOYMENT-GUIDE.md)** - Complete K3s lightweight Kubernetes deployment

## Deployment Guides

### Kubespray (Production Kubernetes)

Complete production-grade Kubernetes deployment using kubespray:

- **[Kubespray Deployment Guide](KUBESPRAY-DEPLOYMENT.md)** - Complete deployment procedures
  - Overview and architecture
  - Prerequisites checklist
  - Infrastructure provisioning with Terraform
  - Kubespray configuration
  - Cluster deployment steps
  - Post-deployment verification
  - Platform components setup

### K3s (Lightweight Kubernetes)

Simplified Kubernetes deployment for rapid setup:

- **[K3s Deployment Guide](DEPLOYMENT-GUIDE.md)** - End-to-end K3s deployment workflow

## Operations and Maintenance

### Kubespray Operations

Day-2 operations for kubespray clusters:

- **[Operations Guide](KUBESPRAY-OPERATIONS.md)** - Node management, upgrades, and maintenance
  - Adding control plane nodes
  - Adding worker nodes
  - Removing nodes
  - Cluster upgrades
  - Health checks
  - Common maintenance tasks

- **[Backup and Restore](KUBESPRAY-BACKUP-RESTORE.md)** - Disaster recovery procedures
  - Etcd backup (manual and automated)
  - Cluster configuration backup
  - Application state backup
  - Restore procedures
  - Disaster recovery scenarios

- **[Troubleshooting Guide](KUBESPRAY-TROUBLESHOOTING.md)** - Issue resolution and diagnostics
  - Deployment issues
  - Networking problems
  - Storage issues
  - Application failures
  - Performance troubleshooting
  - Diagnostic commands
  - Recovery actions

## Architecture and Reference

### Kubespray Architecture

Design documentation for kubespray clusters:

- **[Architecture Documentation](KUBESPRAY-ARCHITECTURE.md)** - Cluster design and components
  - Cluster topology
  - Node specifications
  - Network architecture
  - Storage architecture
  - Component inventory
  - Security model
  - High availability design
  - Scalability considerations

- **[Configuration Reference](KUBESPRAY-CONFIG-REFERENCE.md)** - Complete configuration documentation
  - Inventory structure
  - Group variables
  - Host variables
  - Customization procedures
  - Testing configuration changes

## Security and Secrets Management

Infrastructure-wide security practices:

- **[Vault Setup Guide](VAULT-SETUP.md)** - HashiCorp Vault installation and configuration
  - Vault initialization
  - Unsealing procedures
  - Secret organization
  - Access policies
  - Integration patterns

- **[External Secrets Setup](EXTERNAL-SECRETS-SETUP.md)** - Kubernetes External Secrets Operator
  - ESO installation
  - SecretStore configuration
  - ExternalSecret creation
  - Vault integration

- **[External Secrets Quick Reference](EXTERNAL-SECRETS-QUICKREF.md)** - Fast reference for ESO usage

- **[Security Best Practices](README-SECURITY.md)** - Infrastructure security guidelines
  - Network isolation
  - Credential management
  - Access control
  - Scanning and monitoring

- **[Git History Sanitization](SANITIZING-GIT-HISTORY.md)** - Remove secrets from repository history
  - Sanitization procedures
  - Filter-repo usage
  - Repository cleanup

## Platform Components

Component-specific documentation (see respective directories):

### Storage

- **Democratic CSI**: `/k8s/democratic-csi/README.md`
  - iSCSI storage class
  - NFS storage class
  - FreeNAS/TrueNAS integration

### Networking

- **MetalLB**: `/k8s/metallb/README.md`
  - LoadBalancer services
  - IP address pools
  - Layer 2 configuration

- **Traefik**: `/k8s/traefik/README.md`
  - Ingress controller
  - IngressRoute CRDs
  - Middleware configuration

### Certificates

- **Cert-manager**: `/k8s/cert-manager/README.md`
  - Internal CA setup
  - Certificate issuance
  - Ingress integration

### GitOps

- **ArgoCD**: `/k8s/argocd/README.md`
  - ArgoCD installation
  - Application deployment
  - App of Apps pattern

## Infrastructure as Code

### Terraform

Infrastructure provisioning documentation:

- **Kubespray Cluster**: `/tf/kubespray/README.md` (if exists)
  - VM provisioning
  - Network configuration
  - Vault integration

- **K3s Cluster**: `/tf/kubernetes/` (legacy)

- **Elasticsearch Cluster**: `/tf/lab/`

- **Vault Setup**: `/tf/README-VAULT.md`

### Ansible

Configuration management documentation:

- **Playbooks**: `/ansible/playbooks/`
  - Kubespray deployment wrapper
  - K3s cluster setup
  - Node configuration
  - Package management

## Documentation by Use Case

### First-Time Cluster Deployment

**Kubespray (Recommended for Production):**
1. [Prerequisites](KUBESPRAY-DEPLOYMENT.md#prerequisites)
2. [Quick Start Guide](KUBESPRAY-QUICKSTART.md)
3. [Full Deployment Guide](KUBESPRAY-DEPLOYMENT.md)
4. [Post-Deployment Verification](KUBESPRAY-DEPLOYMENT.md#post-deployment-verification)

**K3s (Lightweight Alternative):**
1. [K3s Deployment Guide](DEPLOYMENT-GUIDE.md)

### Adding Capacity

- [Adding Control Plane Nodes](KUBESPRAY-OPERATIONS.md#adding-control-plane-nodes)
- [Adding Worker Nodes](KUBESPRAY-OPERATIONS.md#adding-worker-nodes)

### Cluster Maintenance

- [Cluster Upgrades](KUBESPRAY-OPERATIONS.md#cluster-upgrades)
- [Health Checks](KUBESPRAY-OPERATIONS.md#cluster-health-checks)
- [Common Maintenance Tasks](KUBESPRAY-OPERATIONS.md#common-maintenance-tasks)

### Disaster Recovery

- [Backup Procedures](KUBESPRAY-BACKUP-RESTORE.md#backup-procedures)
- [Restore Procedures](KUBESPRAY-BACKUP-RESTORE.md#restore-procedures)
- [Recovery Scenarios](KUBESPRAY-BACKUP-RESTORE.md#disaster-recovery-scenarios)

### Troubleshooting

- [Deployment Issues](KUBESPRAY-TROUBLESHOOTING.md#deployment-issues)
- [Networking Issues](KUBESPRAY-TROUBLESHOOTING.md#networking-issues)
- [Storage Issues](KUBESPRAY-TROUBLESHOOTING.md#storage-issues)
- [Application Issues](KUBESPRAY-TROUBLESHOOTING.md#application-issues)
- [Performance Issues](KUBESPRAY-TROUBLESHOOTING.md#cluster-performance)

### Security Setup

- [Vault Installation](VAULT-SETUP.md)
- [Secret Management](README-SECURITY.md)
- [External Secrets Operator](EXTERNAL-SECRETS-SETUP.md)
- [Repository Sanitization](SANITIZING-GIT-HISTORY.md)

## Reference Documentation

### Network Configuration

**Kubespray Cluster:**
- Node network: 192.168.10.0/24
- Service network: 10.233.0.0/18
- Pod network: 10.233.64.0/18
- MetalLB pool: 192.168.100.0/24
- Node IPs: 192.168.10.234-239 (km01-km03, kube01-kube03)

**K3s Cluster:**
- Node IPs: 192.168.10.11-16

**Infrastructure:**
- Vault: 192.168.10.101
- Gateway: 192.168.10.1
- DNS: 192.168.10.1
- Domain: lab.thewortmans.org

### File Locations

**Configuration:**
- Kubespray inventory: `/Users/bret/git/homelab/kubespray/inventory/homelab/`
- Ansible playbooks: `/Users/bret/git/homelab/ansible/playbooks/`
- Kubernetes manifests: `/Users/bret/git/homelab/k8s/`

**Infrastructure:**
- Terraform: `/Users/bret/git/homelab/tf/`
- Kubespray installation: `~/git/kubespray`

### Vault Secret Paths

- Proxmox: `secret/homelab/proxmox/terraform`
- FreeNAS: `secret/homelab/freenas/credentials`
- FreeNAS SSH: `secret/homelab/freenas/ssh`

## Common Commands Reference

### Kubespray Deployment

```bash
# Provision infrastructure
\cd /Users/bret/git/homelab/tf/kubespray/
terraform apply -var-file=terraform.tfvars

# Deploy cluster
\cd /Users/bret/git/homelab/ansible
ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml

# Verify cluster
kubectl get nodes
kubectl get pods -A
```

### Cluster Management

```bash
# Add node
ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini \
  playbooks/add_kubespray_node.yml

# Upgrade cluster
ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini \
  playbooks/upgrade_kubespray_cluster.yml

# Backup etcd
sudo ETCDCTL_API=3 etcdctl snapshot save /var/backups/etcd/snapshot.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem
```

### Diagnostics

```bash
# Check cluster health
kubectl get nodes
kubectl get pods -A
kubectl cluster-info

# Check etcd health
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem

# Check storage
kubectl get storageclass
kubectl get pv
kubectl get pvc -A

# Check networking
kubectl get svc -A
kubectl get ingress -A
kubectl get ipaddresspool -n metallb-system
```

## Contributing to Documentation

When adding or updating documentation:

1. **Follow existing patterns**: Match the style and structure of existing docs
2. **Include examples**: Provide concrete command examples with expected outputs
3. **Cross-reference**: Link to related documentation
4. **Test commands**: Verify all commands work in the current environment
5. **Update this index**: Add new documents to appropriate categories
6. **Use markdown features**: Code blocks, tables, headings for easy navigation

## Getting Help

1. **Check relevant documentation**: Use this index to find the right guide
2. **Review troubleshooting**: See [KUBESPRAY-TROUBLESHOOTING.md](KUBESPRAY-TROUBLESHOOTING.md)
3. **Check component logs**:
   ```bash
   kubectl logs -n <namespace> <pod-name>
   journalctl -u kubelet -f
   ```
4. **Verify configuration**: Review [KUBESPRAY-CONFIG-REFERENCE.md](KUBESPRAY-CONFIG-REFERENCE.md)
5. **Check ArgoCD dashboard**: For application deployment issues
6. **Review Grafana dashboards**: For infrastructure metrics

---

*Last Updated: 2025-11-05*
