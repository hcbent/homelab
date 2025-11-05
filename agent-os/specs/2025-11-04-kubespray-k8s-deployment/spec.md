# Specification: Kubespray Kubernetes Cluster Deployment

## Goal
Deploy a production-grade Kubernetes cluster using kubespray with full integration into existing homelab infrastructure, providing distributed etcd, CNI networking, persistent storage, ingress, GitOps automation, and comprehensive operational documentation.

## User Stories
- As a homelab administrator, I want to deploy a production-grade Kubernetes cluster using kubespray so that I have full control over cluster components and easier maintenance workflows
- As a developer, I want ArgoCD bootstrapped automatically so that I can manage all subsequent applications using GitOps patterns
- As an operator, I want comprehensive documentation for cluster operations so that I can add nodes, upgrade the cluster, and recover from failures

## Specific Requirements

**Infrastructure Provisioning via Terraform**
- Create new Terraform modules in `tf/kubespray/` for provisioning kubespray cluster VMs
- Provision 2 control plane VMs (km02, km03) with VMIDs 221-222, 4 cores, 8GB RAM, 100GB disk
- Provision 3 worker VMs (kube01-kube03) with VMIDs 223-225, 4-8 cores, 8-16GB RAM, 200GB disk
- All VMs clone from ubuntu-25.04 template, use "tank" storage, connect to vmbr0 bridge
- Generate static IP assignments in 192.168.10.x range via cloud-init ipconfig0
- Retrieve Proxmox credentials from Vault at `secret/homelab/proxmox/terraform`
- Output VM IPs and hostnames for dynamic inventory generation

**Bare Metal Control Plane Integration**
- Include existing bare metal node km01 (192.168.10.234, 4 cores, 16GB RAM) as primary control plane
- Configure km01 as first control plane node in kubespray inventory
- Ensure etcd is distributed across all 3 control plane nodes (km01, km02, km03) for HA
- No Terraform provisioning needed for km01, only inventory integration

**Kubespray Configuration Management**
- Create `kubespray/` directory in homelab repo for all kubespray configuration files
- Structure: `kubespray/inventory/homelab/` for inventory files, `kubespray/group_vars/`, `kubespray/host_vars/`
- Configure CNI plugin (Calico or Flannel) for novice-friendly networking
- Configure containerd as container runtime
- Enable CoreDNS for cluster DNS resolution
- Enable cert-manager for internal certificate management
- Disable Prometheus in initial deployment (add later via ArgoCD)

**Ansible Wrapper Playbooks**
- Create wrapper playbooks in `ansible/` directory that invoke kubespray playbooks
- Playbooks: `ansible/deploy_kubespray_cluster.yml` for full deployment
- Playbooks: `ansible/add_kubespray_node.yml` for adding new nodes
- Playbooks: `ansible/upgrade_kubespray_cluster.yml` for cluster upgrades
- Follow existing sequential playbook patterns from K3s setup (00_setup_host.yml style)
- Integrate Vault authentication for retrieving credentials during playbook execution

**Storage Integration with Democratic CSI**
- Deploy Democratic CSI via Helm/ArgoCD for persistent volume provisioning
- Configure FreeNAS iSCSI backend using credentials from Vault at `secret/homelab/freenas/credentials`
- Configure FreeNAS NFS backend for shared storage use cases
- Create storage classes: `freenas-iscsi-csi` (default) and `freenas-nfs-csi`
- Reference existing configuration patterns from `k8s/helm/values/democratic-csi-defaults.yaml`
- Ensure iSCSI path `/etc/iscsi` is configured on all worker nodes

**Networking and Load Balancing**
- Deploy MetalLB for LoadBalancer service type with IP pool 192.168.100.0/24
- Reference existing MetalLB configuration from `k8s/basement/metallb-ippool.yaml`
- Create IPAddressPool and L2Advertisement resources for Layer 2 mode
- Deploy Traefik ingress controller for HTTP(S) routing
- Configure Traefik for internal traffic routing (external handled by NGINX Proxy Manager)

**Vault Integration for Secrets**
- Retrieve all credentials from Vault server at https://192.168.10.101:8200
- Terraform retrieves Proxmox credentials from `secret/homelab/proxmox/terraform`
- Ansible retrieves FreeNAS credentials from `secret/homelab/freenas/credentials` and `secret/homelab/freenas/ssh`
- Deploy External Secrets Operator (ESO) for application-level secret management
- Follow Vault integration patterns from `docs/VAULT-SETUP.md` and `tf/README-VAULT.md`

**ArgoCD Bootstrap Automation**
- Automate ArgoCD installation as part of cluster deployment workflow
- Deploy ArgoCD via kubectl or Helm immediately after cluster initialization
- Configure ArgoCD to watch homelab repository for application definitions
- Bootstrap platform components (MetalLB, Traefik, Democratic CSI, cert-manager) via ArgoCD
- Create ArgoCD Application manifests following existing pattern (`*-app.yaml` files)

**Deployment Workflow and Sequencing**
- Step 1: Run Terraform to provision VMs (km02, km03, kube01-kube03) and output inventory data
- Step 2: Generate kubespray inventory from Terraform outputs and include bare metal km01
- Step 3: Run Ansible wrapper playbook to execute kubespray cluster deployment
- Step 4: Verify cluster health (all nodes ready, etcd quorum, CoreDNS running)
- Step 5: Bootstrap ArgoCD installation
- Step 6: Deploy platform components (storage, networking, ingress) via ArgoCD
- Step 7: Verify all components operational and storage classes available

**Comprehensive Documentation**
- Create `docs/KUBESPRAY-DEPLOYMENT.md` with initial cluster deployment procedures
- Document prerequisites (Vault setup, Proxmox access, DNS configuration)
- Document Terraform provisioning commands and expected outputs
- Document Ansible playbook execution sequence with examples
- Document cluster verification steps (kubectl commands, health checks)
- Create `docs/KUBESPRAY-OPERATIONS.md` for operational procedures
- Document adding new control plane nodes and worker nodes
- Document cluster upgrade procedures using kubespray
- Document backup procedures for etcd and cluster state
- Document restore procedures for disaster recovery scenarios
- Create troubleshooting section for common issues (networking, storage, node failures)

## Out of Scope
- Multi-cluster management or federation (single cluster only)
- Migration of existing K3s workloads to kubespray cluster
- Removal or replacement of existing K3s cluster infrastructure
- Prometheus/Grafana monitoring stack deployment (later phase)
- GPU node configuration and scheduling
- Integration with existing Elasticsearch cluster
- Public-facing Let's Encrypt certificate management (handled by external NGINX Proxy Manager)
- Custom Kubernetes API server configurations beyond kubespray defaults
- Service mesh (Istio, Linkerd) deployment
- Multi-tenancy with namespace isolation policies
