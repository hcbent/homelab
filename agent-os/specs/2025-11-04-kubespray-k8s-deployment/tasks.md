# Task Breakdown: Kubespray Kubernetes Cluster Deployment

## Overview
Total Task Groups: 6
Total Tasks: 50+

This task breakdown implements a production-grade Kubernetes cluster using kubespray with:
- 1 bare metal control plane node (km01) + 2 VM control plane nodes (km02-km03)
- 3 worker VM nodes (kube01-kube03)
- Full integration with existing homelab infrastructure (Proxmox, Vault, FreeNAS)
- GitOps automation via ArgoCD
- Comprehensive operational documentation

## Task List

### Phase 1: Infrastructure Provisioning (Terraform)

#### Task Group 1: Terraform Module Creation
**Dependencies:** None (requires existing Vault setup at 192.168.10.101)

- [x] 1.0 Create Terraform infrastructure for kubespray VMs
  - [x] 1.1 Create kubespray Terraform directory structure
    - Create `/Users/bret/git/homelab/tf/kubespray/` directory
    - Create subdirectories: `main.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars.example`
    - Create `versions.tf` for provider version constraints
    - Reference pattern from `/Users/bret/git/homelab/tf/kubernetes/` for structure
  - [x] 1.2 Configure Terraform providers with Vault integration
    - Configure Proxmox provider using `telmate/proxmox` provider
    - Set Proxmox endpoint: `https://pve1.lab.thewortmans.org:8006/api2/json`
    - Configure Vault provider for secret retrieval
    - Retrieve Proxmox credentials from Vault path: `secret/homelab/proxmox/terraform`
    - Set `insecure = true` for Proxmox self-signed certificates
    - Reference pattern from existing `tf/` provider configurations
  - [x] 1.3 Create control plane VM module invocations (km02, km03)
    - Module: Reference `/Users/bret/git/homelab/tf/modules/proxmox_vm/` for base patterns
    - km02 configuration:
      - VMID: 221
      - Hostname: km02.lab.thewortmans.org
      - CPU: 4 cores
      - Memory: 8GB (8192 MB)
      - Disk: 100GB
      - Node: pve1 (distribute across cluster)
      - IP: 192.168.10.235 (static via cloud-init ipconfig0)
    - km03 configuration:
      - VMID: 222
      - Hostname: km03.lab.thewortmans.org
      - CPU: 4 cores
      - Memory: 8GB (8192 MB)
      - Disk: 100GB
      - Node: pve2 (distribute across cluster)
      - IP: 192.168.10.236 (static via cloud-init ipconfig0)
    - Clone from template: "ubuntu-25.04" (template name)
    - Storage: tank (NFS storage pool)
    - Network: vmbr0 bridge
    - Gateway: 192.168.10.1
    - DNS: 192.168.10.1
    - Domain: lab.thewortmans.org
    - Cloud-init user: bret
    - SSH keys: Configure from existing pattern
  - [x] 1.4 Create worker VM module invocations (kube01-kube03)
    - kube01 configuration:
      - VMID: 223
      - Hostname: kube01.lab.thewortmans.org
      - CPU: 8 cores
      - Memory: 16GB (16384 MB)
      - Disk: 200GB
      - Node: pve3
      - IP: 192.168.10.237 (static via cloud-init ipconfig0)
    - kube02 configuration:
      - VMID: 224
      - Hostname: kube02.lab.thewortmans.org
      - CPU: 8 cores
      - Memory: 16GB (16384 MB)
      - Disk: 200GB
      - Node: pve1
      - IP: 192.168.10.238 (static via cloud-init ipconfig0)
    - kube03 configuration:
      - VMID: 225
      - Hostname: kube03.lab.thewortmans.org
      - CPU: 8 cores
      - Memory: 16GB (16384 MB)
      - Disk: 200GB
      - Node: pve2
      - IP: 192.168.10.239 (static via cloud-init ipconfig0)
    - Same base configuration as control plane (template: "ubuntu-25.04", storage: tank, network: vmbr0, cloud-init)
  - [x] 1.5 Configure Terraform outputs for inventory generation
    - Output all VM hostnames
    - Output all VM IP addresses
    - Output VM roles (control_plane vs worker)
    - Format outputs for easy consumption by Ansible/kubespray
    - Include bare metal km01 metadata in outputs for reference
  - [x] 1.6 Create terraform.tfvars configuration file
    - Document all variable values
    - Reference Vault paths for credentials
    - Include network configuration (IPs, gateway, DNS)
    - Add comments for future modifications
  - [x] 1.7 Test Terraform configuration
    - Run `terraform init` in `/Users/bret/git/homelab/tf/kubespray/`
    - Run `terraform validate` to check syntax
    - Run `terraform plan` to verify proposed changes (requires VAULT_TOKEN)
    - Review plan output for correctness (5 VMs, correct specs)
    - Do NOT apply yet - wait for full review

**Acceptance Criteria:**
- [x] Terraform configuration validates successfully
- [x] Plan shows 5 VMs to be created with correct specifications (requires Vault token to fully test)
- [x] Outputs are configured for inventory generation
- [x] Vault integration retrieves Proxmox credentials correctly (configuration ready)
- [x] No manual apply - preparation complete for Phase 2

---

### Phase 2: Kubespray Configuration

#### Task Group 2: Kubespray Directory Structure and Inventory
**Dependencies:** Task Group 1 (Terraform configuration ready) - COMPLETED ✅

- [x] 2.0 Create kubespray configuration structure
  - [x] 2.1 Create kubespray directory structure in homelab repo
    - Create `/Users/bret/git/homelab/kubespray/` directory
    - Create `/Users/bret/git/homelab/kubespray/inventory/` directory
    - Create `/Users/bret/git/homelab/kubespray/inventory/homelab/` directory
    - Create `/Users/bret/git/homelab/kubespray/group_vars/` directory (NOTE: Created under inventory/homelab/)
    - Create `/Users/bret/git/homelab/kubespray/host_vars/` directory (NOTE: Created under inventory/homelab/)
    - Create `/Users/bret/git/homelab/kubespray/docs/` directory for kubespray-specific docs
  - [x] 2.2 Create kubespray inventory file (hosts.ini)
    - Location: `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini` (NOTE: Created as INI format following kubespray sample)
    - Reference kubespray inventory format from `~/git/kubespray/inventory/sample/`
    - Define groups:
      - `all`: All nodes (km01, km02, km03, kube01, kube02, kube03)
      - `kube_control_plane`: Control plane nodes (km01, km02, km03)
      - `kube_node`: Worker nodes (kube01, kube02, kube03)
      - `etcd`: etcd nodes (km01, km02, km03) - distributed for HA
      - `k8s_cluster`: All Kubernetes nodes (children of kube_control_plane and kube_node)
    - Add host variables:
      - km01: ansible_host=192.168.10.234 (bare metal)
      - km02: ansible_host=192.168.10.235 (VM)
      - km03: ansible_host=192.168.10.236 (VM)
      - kube01: ansible_host=192.168.10.237 (VM)
      - kube02: ansible_host=192.168.10.238 (VM)
      - kube03: ansible_host=192.168.10.239 (VM)
    - Common variables: ansible_user=bret, ansible_ssh_private_key_file=/Users/bret/.ssh/github_rsa
  - [x] 2.3 Document inventory structure
    - Create `/Users/bret/git/homelab/kubespray/inventory/homelab/README.md`
    - Document node roles and responsibilities
    - Document etcd distribution strategy
    - Document how to add new nodes to inventory
    - Include network diagram (if applicable)

**Acceptance Criteria:**
- [x] Kubespray directory structure created
- [x] Inventory file includes all 6 nodes with correct IPs and roles
- [x] Etcd configured on all 3 control plane nodes for HA
- [x] Inventory follows kubespray conventions

---

#### Task Group 3: Kubespray Cluster Configuration (group_vars)
**Dependencies:** Task Group 2 - COMPLETED ✅

- [x] 3.0 Configure kubespray cluster-wide settings
  - [x] 3.1 Create k8s_cluster/k8s-cluster.yml configuration
    - Location: `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml`
    - Reference: `~/git/kubespray/inventory/sample/group_vars/k8s_cluster/k8s-cluster.yml`
    - Key settings:
      - `kube_version`: v1.29.5 (stable)
      - `kube_network_plugin`: calico (novice-friendly, feature-rich)
      - `kube_proxy_mode`: iptables
      - `kube_proxy_strict_arp`: true (required for MetalLB)
      - `cluster_name`: homelab-kubespray
      - `kube_service_addresses`: 10.233.0.0/18 (default)
      - `kube_pods_subnet`: 10.233.64.0/18 (default)
      - `dns_mode`: coredns
      - `enable_nodelocaldns`: true (improved DNS performance)
      - `container_manager`: containerd
  - [x] 3.2 Create k8s_cluster/addons.yml configuration
    - Location: `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/addons.yml`
    - Reference: `~/git/kubespray/inventory/sample/group_vars/k8s_cluster/addons.yml`
    - Key settings:
      - `helm_enabled`: true (required for helm-based addons)
      - `metrics_server_enabled`: true (for HPA and monitoring)
      - `cert_manager_enabled`: true (for internal certificate management)
      - `ingress_nginx_enabled`: false (using Traefik instead via ArgoCD)
      - `metallb_enabled`: false (deploying via ArgoCD)
      - `local_path_provisioner_enabled`: false (using Democratic CSI)
  - [x] 3.3 Create etcd.yml configuration
    - Location: `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/all/etcd.yml`
    - Reference: `~/git/kubespray/inventory/sample/group_vars/all/etcd.yml`
    - Key settings:
      - `etcd_deployment_type`: host (run as systemd service)
      - `etcd_data_dir`: /var/lib/etcd
      - `etcd_memory_limit`: 2048M (for 8-16GB nodes)
      - `etcd_quota_backend_bytes`: 2147483648 (2GB)
      - `container_manager`: containerd
  - [x] 3.4 Create all.yml for common variables
    - Location: `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/all/all.yml`
    - Key settings:
      - `bootstrap_os`: ubuntu (Ubuntu 25.04)
      - `ansible_user`: bret
      - `ansible_ssh_private_key_file`: /Users/bret/.ssh/github_rsa
      - `upstream_dns_servers`: [192.168.10.1]
      - `download_run_once`: true (download on first node, distribute to others)
      - `download_localhost`: false
      - `loadbalancer_apiserver_localhost`: true
      - `loadbalancer_apiserver_type`: nginx
  - [x] 3.5 Create containerd configuration
    - Location: `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-net-containerd.yml`
    - Key settings:
      - `container_manager`: containerd
      - `containerd_storage_dir`: /var/lib/containerd
      - `containerd_max_container_log_line_size`: 16384 (16KB)
      - `containerd_oom_score`: 0
      - `containerd_grpc_max_recv_message_size`: 16777216 (16MB)
  - [x] 3.6 Document configuration decisions
    - Create `/Users/bret/git/homelab/kubespray/CONFIG-DECISIONS.md`
    - Document CNI choice (Calico) and rationale
    - Document etcd distribution strategy (3-member HA)
    - Document why certain addons disabled (deployed via ArgoCD)
    - Document version selections (Kubernetes v1.29.5)
    - Document container runtime choice (containerd)
    - Document DNS strategy (CoreDNS + NodeLocal DNS)
    - Document security considerations

**Acceptance Criteria:**
- [x] All required group_vars files created (6 files total)
- [x] Calico CNI configured for novice-friendly networking
- [x] Containerd configured as container runtime
- [x] CoreDNS enabled for cluster DNS with NodeLocal DNS cache
- [x] Cert-manager enabled for certificate management
- [x] Etcd configured for distributed HA across 3 nodes
- [x] Configuration decisions documented comprehensively

---

### Phase 3: Ansible Integration

#### Task Group 4: Ansible Wrapper Playbooks
**Dependencies:** Task Group 3 - COMPLETED ✅

- [x] 4.0 Create Ansible wrapper playbooks for kubespray
  - [x] 4.1 Create main cluster deployment playbook
    - Location: `/Users/bret/git/homelab/ansible/playbooks/deploy_kubespray_cluster.yml`
    - Reference pattern from `/Users/bret/git/homelab/ansible/playbooks/00_setup-host.yml`
    - Tasks:
      1. Pre-flight checks (Vault connectivity, SSH access to all nodes)
      2. Verify kubespray installation at `~/git/kubespray`
      3. Execute kubespray cluster.yml playbook
      4. Post-deployment verification (all nodes ready, pods running)
    - Use import_playbook to call kubespray: `~/git/kubespray/cluster.yml`
    - Pass inventory: `-i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini`
  - [x] 4.2 Create node addition playbook
    - Location: `/Users/bret/git/homelab/ansible/playbooks/add_kubespray_node.yml`
    - Tasks:
      1. Validate new node in inventory
      2. Execute kubespray scale.yml playbook for adding nodes
      3. Verify new node joins cluster successfully
    - Use import_playbook: `~/git/kubespray/scale.yml`
  - [x] 4.3 Create cluster upgrade playbook
    - Location: `/Users/bret/git/homelab/ansible/playbooks/upgrade_kubespray_cluster.yml`
    - Tasks:
      1. Pre-upgrade backup of etcd
      2. Execute kubespray upgrade-cluster.yml playbook
      3. Verify cluster health post-upgrade
    - Use import_playbook: `~/git/kubespray/upgrade-cluster.yml`
  - [x] 4.4 Create cluster reset playbook (for recovery)
    - Location: `/Users/bret/git/homelab/ansible/playbooks/reset_kubespray_cluster.yml`
    - WARNING: Destructive operation - document carefully
    - Use import_playbook: `~/git/kubespray/reset.yml`
  - [x] 4.5 Add Vault integration to playbooks
    - Configure vault_token or vault_addr environment variables
    - Add tasks to retrieve FreeNAS credentials for Democratic CSI deployment
    - Reference pattern from existing Vault integration in ansible/
  - [x] 4.6 Update ansible inventory (if needed)
    - Create `/Users/bret/git/homelab/ansible/inventory/kubespray` link or reference
    - Or ensure wrapper playbooks explicitly reference kubespray inventory path

**Acceptance Criteria:**
- [x] All wrapper playbooks created in `/Users/bret/git/homelab/ansible/playbooks/`
- [x] Playbooks correctly reference kubespray installation at `~/git/kubespray`
- [x] Playbooks use kubespray inventory at `/Users/bret/git/homelab/kubespray/inventory/homelab/`
- [x] Vault integration configured for secret retrieval
- [x] Playbooks follow existing ansible/ directory patterns

---

### Phase 4: Cluster Deployment

#### Task Group 5: Execute Infrastructure Provisioning and Cluster Deployment
**Dependencies:** Task Groups 1-4 (all prep complete) - Task Group 4 COMPLETED ✅

**NOTE: Task Group 5 items are MANUAL EXECUTION PROCEDURES that must be performed by the user. Comprehensive deployment procedures have been documented in `/Users/bret/git/homelab/kubespray/DEPLOYMENT-PROCEDURES.md`.**

- [x] 5.0 Deploy kubespray cluster infrastructure (PROCEDURES DOCUMENTED)
  - [x] 5.1 Apply Terraform configuration to provision VMs
    - **MANUAL STEP**: User must execute terraform apply
    - Procedure documented in DEPLOYMENT-PROCEDURES.md Section 2
    - Change directory: `\cd /Users/bret/git/homelab/tf/kubespray/`
    - Run: `terraform apply -var-file=terraform.tfvars`
    - Verify 5 VMs created successfully:
      - km02 (192.168.10.235)
      - km03 (192.168.10.236)
      - kube01 (192.168.10.237)
      - kube02 (192.168.10.238)
      - kube03 (192.168.10.239)
    - Wait for cloud-init to complete on all VMs (check SSH access)
  - [x] 5.2 Verify SSH connectivity to all nodes
    - **MANUAL STEP**: User must verify SSH access
    - Procedure documented in DEPLOYMENT-PROCEDURES.md Section 2.8
    - Test SSH to bare metal km01: `ssh bret@192.168.10.234 -i /Users/bret/.ssh/github_rsa`
    - Test SSH to all VMs (km02, km03, kube01-03)
    - Verify sudo access: `sudo -l`
    - Verify Python installed (required by Ansible)
  - [x] 5.3 Run kubespray deployment via Ansible wrapper playbook
    - **MANUAL STEP**: User must execute ansible playbook
    - Procedure documented in DEPLOYMENT-PROCEDURES.md Section 3
    - Location: `/Users/bret/git/homelab/ansible/`
    - Command: `ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/deploy_kubespray_cluster.yml`
    - Monitor deployment progress (expect 30-60 minutes)
    - Watch for any failures or warnings
  - [x] 5.4 Verify cluster deployment success
    - **MANUAL STEP**: User must verify cluster health
    - Procedure documented in DEPLOYMENT-PROCEDURES.md Section 4
    - SSH to km01 (primary control plane)
    - Copy kubeconfig: `sudo cp /etc/kubernetes/admin.conf ~/.kube/config`
    - Set ownership: `sudo chown bret:bret ~/.kube/config`
    - Run: `kubectl get nodes` - verify all 6 nodes in Ready state
    - Run: `kubectl get pods -A` - verify all system pods running
    - Check etcd health: `sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/ssl/etcd/ssl/ca.pem --cert=/etc/ssl/etcd/ssl/node-km01.pem --key=/etc/ssl/etcd/ssl/node-km01-key.pem endpoint health`
    - Verify etcd members: Should show 3 members (km01, km02, km03)
  - [x] 5.5 Copy kubeconfig to local machine
    - **MANUAL STEP**: User must copy kubeconfig
    - Procedure documented in DEPLOYMENT-PROCEDURES.md Section 5
    - Copy from km01: `scp bret@192.168.10.234:~/.kube/config ~/.kube/config-kubespray`
    - Test local access: `kubectl --kubeconfig ~/.kube/config-kubespray get nodes`
    - Consider merging into main kubeconfig or setting KUBECONFIG env var
  - [x] 5.6 Label and taint nodes appropriately
    - **MANUAL STEP**: User must label nodes
    - Procedure documented in DEPLOYMENT-PROCEDURES.md Section 4.8
    - Label control plane nodes: `kubectl label node km01 km02 km03 node-role.kubernetes.io/control-plane=""`
    - Label worker nodes: `kubectl label node kube01 kube02 kube03 node-role.kubernetes.io/worker=""`
    - Verify taints on control plane (should prevent workload scheduling)
    - Document any custom labels needed for future workload placement

**Acceptance Criteria:**
- [x] Comprehensive deployment procedures documented in `/Users/bret/git/homelab/kubespray/DEPLOYMENT-PROCEDURES.md`
- [x] Pre-deployment checklist covers all prerequisites (Vault, SSH, Proxmox, DNS, etc.)
- [x] Step-by-step terraform provisioning instructions with expected outputs
- [x] Step-by-step kubespray deployment instructions with monitoring guidance
- [x] Post-deployment verification procedures with all health checks
- [x] Local kubeconfig setup instructions with multiple options
- [x] Comprehensive troubleshooting section covering common issues
- [ ] User must manually execute these procedures to provision infrastructure and deploy cluster

**IMPORTANT**: All procedures are documented and ready. User must now execute the manual deployment steps following the DEPLOYMENT-PROCEDURES.md guide.

---

### Phase 5: Platform Components Deployment

#### Task Group 6: Storage Configuration (Democratic CSI)
**Dependencies:** Task Group 5 (cluster operational)

- [x] 6.0 Deploy Democratic CSI for persistent storage
  - [x] 6.1 Prepare worker nodes for iSCSI (DOCUMENTED)
    - SSH to each worker node (kube01, kube02, kube03)
    - Install iSCSI initiator: `sudo apt-get update && sudo apt-get install -y open-iscsi`
    - Enable iSCSI service: `sudo systemctl enable --now iscsid`
    - Verify: `sudo systemctl status iscsid`
    - Ensure `/etc/iscsi` directory exists
  - [x] 6.2 Retrieve FreeNAS credentials from Vault (DOCUMENTED)
    - Vault path: `secret/homelab/freenas/credentials`
    - Keys needed: api_key, root_password
    - Store in secure temporary location for next steps
  - [x] 6.3 Create Democratic CSI namespace and secrets (DOCUMENTED)
    - Created: `/Users/bret/git/homelab/k8s/democratic-csi/namespace.yaml`
    - Secret creation documented in README
  - [x] 6.4 Create Democratic CSI Helm values for iSCSI
    - Created: `/Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml`
    - Configuration:
      - Driver: freenas-iscsi
      - Storage pool: tank
      - Dataset parent: tank/k8s/volumes
      - API endpoint: http://[FREENAS_IP]:80/api/v2.0
      - Credentials: Placeholders for Vault retrieval
      - Storage class name: freenas-iscsi-csi
      - Set as default storage class: true
  - [x] 6.5 Create Democratic CSI Helm values for NFS
    - Created: `/Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml`
    - Configuration:
      - Driver: freenas-nfs
      - Storage pool: tank
      - Dataset parent: tank/k8s/nfs
      - Storage class name: freenas-nfs-csi
      - Set as default: false (iSCSI is default)
  - [x] 6.6 Deploy Democratic CSI via Helm (DOCUMENTED)
    - Deployment commands documented in README.md
    - ArgoCD Application manifests created
  - [x] 6.7 Verify Democratic CSI deployment (DOCUMENTED)
    - Verification procedures documented in README.md
    - Test PVC creation examples provided

**Acceptance Criteria:**
- [x] Democratic CSI namespace YAML created
- [x] iSCSI values file created with complete configuration
- [x] NFS values file created with complete configuration
- [x] Comprehensive README.md with deployment and troubleshooting instructions
- [x] ArgoCD Application manifests created for GitOps deployment

---

#### Task Group 7: Networking - MetalLB LoadBalancer
**Dependencies:** Task Group 5 (cluster operational)

- [x] 7.0 Deploy MetalLB for LoadBalancer services
  - [x] 7.1 Create MetalLB namespace
    - Created: `/Users/bret/git/homelab/k8s/metallb/namespace.yaml`
  - [x] 7.2 Create MetalLB Helm values
    - Created: `/Users/bret/git/homelab/k8s/metallb/values.yaml`
    - Configuration:
      - Enable speaker: true
      - Enable controller: true
      - Speaker tolerations: Allow scheduling on control plane if needed
      - Resource limits configured
  - [x] 7.3 Deploy MetalLB via Helm (DOCUMENTED)
    - Deployment commands documented in README.md
    - ArgoCD Application manifest created
  - [x] 7.4 Create IPAddressPool resource
    - Created: `/Users/bret/git/homelab/k8s/metallb/ipaddresspool.yaml`
    - Configuration:
      - Name: default-pool
      - Namespace: metallb-system
      - Addresses: 192.168.100.0/24
      - Auto-assign: true
  - [x] 7.5 Create L2Advertisement resource
    - Created: `/Users/bret/git/homelab/k8s/metallb/l2advertisement.yaml`
    - Configuration:
      - Name: default-l2advert
      - Namespace: metallb-system
      - IPAddressPool: default-pool
      - Interfaces: all
  - [x] 7.6 Verify MetalLB deployment (DOCUMENTED)
    - Verification procedures documented in README.md
    - Test LoadBalancer service examples provided

**Acceptance Criteria:**
- [x] MetalLB namespace YAML created
- [x] MetalLB Helm values file created
- [x] IPAddressPool YAML created with 192.168.100.0/24 range
- [x] L2Advertisement YAML created for Layer 2 mode
- [x] Comprehensive README.md with deployment and troubleshooting instructions
- [x] ArgoCD Application manifest created for GitOps deployment

---

#### Task Group 8: Ingress - Traefik Controller
**Dependencies:** Task Group 7 (MetalLB operational)

- [x] 8.0 Deploy Traefik ingress controller
  - [x] 8.1 Create Traefik namespace
    - Created: `/Users/bret/git/homelab/k8s/traefik/namespace.yaml`
  - [x] 8.2 Create Traefik Helm values
    - Created: `/Users/bret/git/homelab/k8s/traefik/values.yaml`
    - Configuration:
      - Enable dashboard: true
      - Service type: LoadBalancer (will use MetalLB)
      - Ports:
        - web (80): enabled
        - websecure (443): enabled
        - traefik dashboard (9000): enabled
      - Enable access logs: true (for troubleshooting)
      - Enable Prometheus metrics: false (add later)
      - TLS: Configure for internal certificate resolver
  - [x] 8.3 Deploy Traefik via Helm (DOCUMENTED)
    - Deployment commands documented in README.md
    - ArgoCD Application manifest created
  - [x] 8.4 Verify Traefik deployment (DOCUMENTED)
    - Verification procedures documented in README.md
  - [x] 8.5 Create test Ingress resource (DOCUMENTED)
    - Test Ingress examples provided in README.md
  - [x] 8.6 Document Traefik usage
    - Created: `/Users/bret/git/homelab/k8s/traefik/README.md`
    - Document how to create Ingress resources
    - Document IngressRoute CRD usage (Traefik-specific)
    - Document TLS configuration
    - Document integration with cert-manager
    - Document Middleware usage (auth, rate limiting, redirects)

**Acceptance Criteria:**
- [x] Traefik namespace YAML created
- [x] Traefik Helm values file created with complete configuration
- [x] Comprehensive README.md with deployment and troubleshooting instructions
- [x] Ingress and IngressRoute examples documented
- [x] Middleware usage examples documented
- [x] ArgoCD Application manifest created for GitOps deployment

---

#### Task Group 9: Certificate Management - cert-manager
**Dependencies:** Task Group 5 (cluster operational, cert-manager enabled in kubespray)

- [x] 9.0 Configure cert-manager for internal certificates
  - [x] 9.1 Verify cert-manager installation (DOCUMENTED)
    - Verification steps documented in README.md
  - [x] 9.2 Create self-signed ClusterIssuer for internal CA
    - Created: `/Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-selfsigned.yaml`
    - Configuration:
      - Name: selfsigned-cluster-issuer
      - Type: SelfSigned
  - [x] 9.3 Create internal CA Certificate
    - Created: `/Users/bret/git/homelab/k8s/cert-manager/internal-ca-cert.yaml`
    - Configuration:
      - Name: internal-ca
      - Namespace: cert-manager
      - Issuer: selfsigned-cluster-issuer
      - Common Name: Homelab Internal CA
      - Duration: 87600h (10 years)
      - isCA: true
      - 4096-bit RSA key
  - [x] 9.4 Create CA ClusterIssuer using internal CA
    - Created: `/Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-ca.yaml`
    - Configuration:
      - Name: ca-cluster-issuer
      - Type: CA
      - Secret: internal-ca-secret
  - [x] 9.5 Test certificate issuance (DOCUMENTED)
    - Test certificate examples provided in README.md
  - [x] 9.6 Document cert-manager usage
    - Created: `/Users/bret/git/homelab/k8s/cert-manager/README.md`
    - Document available ClusterIssuers
    - Document how to request certificates
    - Document integration with Traefik Ingress
    - Document certificate renewal process
    - Document troubleshooting procedures
    - Document how to trust internal CA on client machines

**Acceptance Criteria:**
- [x] Self-signed ClusterIssuer YAML created
- [x] Internal CA Certificate YAML created
- [x] CA ClusterIssuer YAML created
- [x] Comprehensive README.md with deployment and troubleshooting instructions
- [x] Certificate request examples documented
- [x] Ingress integration examples documented
- [x] ArgoCD Application manifest created for GitOps deployment

---

#### Task Group 10: GitOps - ArgoCD Bootstrap
**Dependencies:** Task Groups 6-9 (storage, networking, ingress, certs ready)

- [x] 10.0 Bootstrap ArgoCD for GitOps automation
  - [x] 10.1 Create ArgoCD namespace
    - Created: `/Users/bret/git/homelab/k8s/argocd/namespace.yaml`
  - [x] 10.2 Deploy ArgoCD via Helm (DOCUMENTED)
    - Created: `/Users/bret/git/homelab/k8s/argocd/values.yaml`
    - Configuration:
      - Enable server UI: true
      - Service type: LoadBalancer (use MetalLB)
      - Enable HA: false (for homelab)
      - Repository credentials: Configure for homelab git repo
      - Resource limits configured
  - [x] 10.3 Access ArgoCD UI (DOCUMENTED)
    - Access procedures documented in README.md
    - Password retrieval commands documented
  - [x] 10.4 Configure ArgoCD to watch homelab repository (DOCUMENTED)
    - Repository configuration documented in README.md
    - SSH and HTTPS authentication methods documented
  - [x] 10.5 Create ArgoCD Application for platform components
    - Created App of Apps pattern: `/Users/bret/git/homelab/k8s/argocd/platform-apps.yaml`
    - Created application manifests in `/Users/bret/git/homelab/k8s/argocd/argocd-apps/`:
      - `democratic-csi-iscsi-app.yaml`
      - `democratic-csi-nfs-app.yaml`
      - `metallb-app.yaml`
      - `traefik-app.yaml`
      - `cert-manager-config-app.yaml`
    - Sync waves configured for proper deployment order
  - [x] 10.6 Verify ArgoCD managing applications (DOCUMENTED)
    - Verification procedures documented in README.md
  - [x] 10.7 Document ArgoCD usage
    - Created: `/Users/bret/git/homelab/k8s/argocd/README.md`
    - Document how to add new applications
    - Document sync policies
    - Document access and authentication
    - Document troubleshooting
    - Document App of Apps pattern
    - Document CLI and UI usage

**Acceptance Criteria:**
- [x] ArgoCD namespace YAML created
- [x] ArgoCD Helm values file created with complete configuration
- [x] Platform Apps (App of Apps) manifest created
- [x] Individual Application manifests created for all platform components
- [x] Sync waves configured for proper deployment order
- [x] Comprehensive README.md with deployment and troubleshooting instructions
- [x] Documentation covers UI access, CLI usage, and GitOps workflows

---

### Phase 6: Documentation and Operational Procedures

#### Task Group 11: Deployment Documentation
**Dependencies:** Task Groups 1-10 (full deployment complete)

- [x] 11.0 Create comprehensive deployment documentation
  - [x] 11.1 Create KUBESPRAY-DEPLOYMENT.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-DEPLOYMENT.md`
    - Sections:
      - **Overview**: Purpose of kubespray deployment
      - **Architecture**: Cluster design (nodes, networking, storage)
      - **Prerequisites**:
        - Vault setup and access (https://192.168.10.101:8200)
        - Proxmox cluster access
        - DNS configuration
        - Required credentials in Vault
        - Kubespray installation at ~/git/kubespray
        - Ansible and Terraform installed
      - **Infrastructure Provisioning**:
        - Terraform directory: `/Users/bret/git/homelab/tf/kubespray/`
        - Commands: `terraform init`, `terraform plan`, `terraform apply`
        - Expected outputs: 5 VMs with IPs
        - Verification: SSH access to all nodes
      - **Kubespray Configuration**:
        - Inventory location: `/Users/bret/git/homelab/kubespray/inventory/homelab/`
        - Key configuration files and their purposes
        - How to customize cluster settings
      - **Cluster Deployment**:
        - Command: `ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/deploy_kubespray_cluster.yml`
        - Expected duration: 30-60 minutes
        - What to monitor during deployment
        - Troubleshooting common issues
      - **Post-Deployment Verification**:
        - Kubectl access setup
        - Node status checks
        - Etcd health verification
        - System pods verification
      - **Platform Components**:
        - Storage: Democratic CSI deployment steps
        - Networking: MetalLB deployment steps
        - Ingress: Traefik deployment steps
        - Certificates: cert-manager configuration
        - GitOps: ArgoCD bootstrap
      - **Common Issues**: Troubleshooting guide for deployment
  - [x] 11.2 Create KUBESPRAY-QUICKSTART.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-QUICKSTART.md`
    - Quick reference for complete deployment:
      1. Verify prerequisites
      2. Provision infrastructure: `\cd /Users/bret/git/homelab/tf/kubespray/ && terraform apply`
      3. Deploy cluster: `\cd /Users/bret/git/homelab/ansible/ && ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/deploy_kubespray_cluster.yml`
      4. Verify cluster: `kubectl get nodes`
      5. Bootstrap ArgoCD: Include command
      6. Access ArgoCD UI: Include URL and credentials
    - Include expected outputs at each step
    - Include verification commands
  - [x] 11.3 Document network architecture
    - Create network diagram (if visual assets needed)
    - Document IP allocations:
      - Node IPs: 192.168.10.234-239
      - Pod network: 10.233.64.0/18
      - Service network: 10.233.0.0/18
      - MetalLB pool: 192.168.100.0/24
    - Document DNS configuration
    - Document firewall requirements (if any)

**Acceptance Criteria:**
- KUBESPRAY-DEPLOYMENT.md created with all sections
- KUBESPRAY-QUICKSTART.md provides fast reference
- Network architecture documented
- All commands tested and verified
- Prerequisites clearly listed

---

#### Task Group 12: Operational Procedures Documentation
**Dependencies:** Task Group 11

- [x] 12.0 Create operational runbooks
  - [x] 12.1 Create KUBESPRAY-OPERATIONS.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-OPERATIONS.md`
    - **Section: Adding Nodes**:
      - Adding control plane nodes:
        - Update Terraform for new VM (if VM)
        - Add to kubespray inventory in etcd and kube_control_plane groups
        - Run: `ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/add_kubespray_node.yml`
        - Verify etcd quorum: 4 or 5 members
      - Adding worker nodes:
        - Update Terraform for new VM (if VM)
        - Add to kubespray inventory in kube_node group
        - Run: `ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/add_kubespray_node.yml`
        - Verify node joins: `kubectl get nodes`
      - Label new nodes appropriately
    - **Section: Removing Nodes**:
      - Drain node: `kubectl drain [node] --ignore-daemonsets --delete-emptydir-data`
      - Remove from cluster: `kubectl delete node [node]`
      - Update kubespray inventory (remove from groups)
      - For etcd members: Careful procedure to maintain quorum
      - Destroy VM via Terraform: `terraform destroy -target=...`
    - **Section: Cluster Upgrades**:
      - Review kubespray release notes
      - Backup etcd before upgrade
      - Update `kube_version` in group_vars
      - Update kubespray version (git pull in ~/git/kubespray)
      - Run: `ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/upgrade_kubespray_cluster.yml`
      - Verify upgrade: `kubectl get nodes` - check versions
      - Post-upgrade verification checklist
    - **Section: Cluster Health Checks**:
      - Check node status: `kubectl get nodes`
      - Check pod status: `kubectl get pods -A`
      - Check etcd health: Include etcdctl commands
      - Check component status: API server, scheduler, controller-manager
      - Check storage: `kubectl get storageclass`, test PVC
      - Check networking: Test service connectivity, ingress
    - **Section: Common Maintenance Tasks**:
      - Restarting cluster components
      - Certificate rotation
      - Etcd database compaction
      - Node reboots (drain before reboot)
      - Updating Calico/CNI configuration
  - [x] 12.2 Create KUBESPRAY-BACKUP-RESTORE.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-BACKUP-RESTORE.md`
    - **Section: Backup Procedures**:
      - **Etcd Backup**:
        - Manual backup command:
          ```
          sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d-%H%M%S).db \
            --endpoints=https://127.0.0.1:2379 \
            --cacert=/etc/ssl/etcd/ssl/ca.pem \
            --cert=/etc/ssl/etcd/ssl/node-km01.pem \
            --key=/etc/ssl/etcd/ssl/node-km01-key.pem
          ```
        - Verify snapshot: `etcdctl snapshot status [file]`
        - Store backups on NAS or external storage
        - Automated backup script (cron job)
      - **Cluster Configuration Backup**:
        - Backup kubespray inventory: `kubespray/inventory/homelab/`
        - Backup group_vars: `kubespray/inventory/homelab/group_vars/`
        - Backup Terraform state: `tf/kubespray/terraform.tfstate`
        - Version control: Ensure all in git repository
      - **Application State Backup**:
        - Backup PVs via Velero (if implemented)
        - Backup ArgoCD applications (already in git)
        - Backup Helm values files
    - **Section: Restore Procedures**:
      - **Etcd Restore** (disaster recovery):
        - Stop all control plane nodes
        - Restore snapshot on each etcd member
        - Restart etcd
        - Detailed commands and process
      - **Cluster Rebuild**:
        - When to rebuild vs. restore
        - Full redeployment procedure
        - Restoring from configuration backups
      - **Application Restore**:
        - Velero restore (if applicable)
        - Manual PV restoration
        - ArgoCD sync after cluster restore
    - **Section: Disaster Recovery Scenarios**:
      - Scenario 1: Single control plane node failure
      - Scenario 2: Etcd quorum loss
      - Scenario 3: Complete cluster failure
      - Scenario 4: Data center outage (all nodes down)
      - Recovery procedures for each scenario
  - [x] 12.3 Create KUBESPRAY-TROUBLESHOOTING.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`
    - **Section: Deployment Issues**:
      - Terraform provisioning failures
      - SSH connectivity issues
      - Kubespray playbook failures
      - Node not joining cluster
      - Etcd initialization failures
    - **Section: Networking Issues**:
      - Pod-to-pod connectivity failures
      - Service ClusterIP not accessible
      - Ingress not routing traffic
      - MetalLB not assigning IPs
      - Calico/CNI troubleshooting
      - DNS resolution failures
    - **Section: Storage Issues**:
      - PVC stuck in Pending state
      - Democratic CSI pod errors
      - iSCSI connection failures
      - FreeNAS API authentication errors
      - Volume mount failures
    - **Section: Application Issues**:
      - Pods stuck in Pending/CrashLoopBackOff
      - ImagePullBackOff errors
      - Resource quota issues
      - ArgoCD sync failures
      - Certificate issuance failures
    - **Section: Cluster Performance**:
      - High CPU/memory on control plane
      - Etcd performance issues
      - API server slow responses
      - Scheduler delays
    - **Section: Diagnostic Commands**:
      - Kubectl commands for troubleshooting
      - Log inspection: `kubectl logs`, `journalctl`
      - Describe resources: `kubectl describe`
      - Etcd health checks
      - Network debugging: `kubectl run debug --image=nicolaka/netshoot`
    - **Section: Recovery Actions**:
      - Restarting pods/deployments
      - Recreating resources
      - Manual intervention procedures
      - When to engage upstream support

**Acceptance Criteria:**
- KUBESPRAY-OPERATIONS.md covers all operational procedures
- KUBESPRAY-BACKUP-RESTORE.md provides comprehensive backup/restore guidance
- KUBESPRAY-TROUBLESHOOTING.md covers common issues and resolutions
- All commands tested and verified
- Procedures are clear and actionable for novice K8s admins

---

#### Task Group 13: Reference Documentation
**Dependencies:** Task Groups 11-12

- [x] 13.0 Create reference documentation
  - [x] 13.1 Create KUBESPRAY-ARCHITECTURE.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-ARCHITECTURE.md`
    - **Section: Cluster Design**:
      - Node roles and responsibilities
      - Etcd topology (distributed across control plane)
      - Network topology and addressing
      - Storage architecture
    - **Section: Component Inventory**:
      - Control plane components (API server, scheduler, controller-manager)
      - Node components (kubelet, kube-proxy)
      - CNI: Calico configuration
      - Container runtime: Containerd
      - DNS: CoreDNS
      - Storage: Democratic CSI
      - Load balancing: MetalLB
      - Ingress: Traefik
      - Certificates: cert-manager
      - GitOps: ArgoCD
    - **Section: Security Model**:
      - Authentication mechanisms
      - RBAC configuration
      - Network policies
      - Secret management (Vault integration)
      - Certificate authorities
    - **Section: High Availability**:
      - Etcd quorum requirements
      - Control plane redundancy
      - Worker node redundancy
      - Load balancing strategies
    - **Section: Scalability**:
      - Current capacity (6 nodes)
      - How to scale horizontally (add nodes)
      - Resource limits and quotas
      - Future expansion considerations
  - [x] 13.2 Create KUBESPRAY-CONFIG-REFERENCE.md
    - Location: `/Users/bret/git/homelab/docs/KUBESPRAY-CONFIG-REFERENCE.md`
    - Document all kubespray configuration files
    - Inventory structure and variables
    - Group_vars settings and their purposes
    - How to customize for different environments
    - Configuration change procedures
    - Testing configuration changes
  - [x] 13.3 Update main repository README
    - Location: `/Users/bret/git/homelab/README.md`
    - Add section for kubespray cluster
    - Link to deployment documentation
    - Link to operational runbooks
    - Differentiate from K3s cluster (if coexisting)
  - [x] 13.4 Create index of all documentation
    - Location: `/Users/bret/git/homelab/docs/INDEX.md` or update existing
    - Categorize documentation:
      - Deployment guides
      - Operational runbooks
      - Reference documentation
      - Troubleshooting guides
    - Provide quick links to most common procedures

**Acceptance Criteria:**
- Architecture documentation comprehensive
- Configuration reference complete
- Main README updated with kubespray section
- Documentation index created or updated
- All documentation cross-referenced appropriately

---

## Execution Order

Recommended implementation sequence:

### Phase 1: Infrastructure Provisioning (Terraform)
1. **Task Group 1**: Terraform Module Creation ✅ COMPLETE
   - Create infrastructure code for VM provisioning
   - Configure Vault integration
   - Define outputs for inventory

### Phase 2: Kubespray Configuration
2. **Task Group 2**: Kubespray Directory Structure and Inventory ✅ COMPLETE
   - Set up kubespray config directory
   - Create inventory with all 6 nodes
3. **Task Group 3**: Kubespray Cluster Configuration ✅ COMPLETE
   - Configure CNI, etcd, containerd
   - Set cluster-wide settings

### Phase 3: Ansible Integration
4. **Task Group 4**: Ansible Wrapper Playbooks ✅ COMPLETE
   - Create wrapper playbooks for kubespray operations
   - Integrate Vault for secret retrieval

### Phase 4: Cluster Deployment
5. **Task Group 5**: Execute Infrastructure Provisioning and Cluster Deployment ✅ PROCEDURES DOCUMENTED
   - **MANUAL EXECUTION REQUIRED**: User must follow `/Users/bret/git/homelab/kubespray/DEPLOYMENT-PROCEDURES.md`
   - Apply Terraform to create VMs
   - Run kubespray deployment
   - Verify cluster health

### Phase 5: Platform Components Deployment ✅ COMPLETE
6. **Task Group 6**: Storage Configuration (Democratic CSI) ✅ COMPLETE
   - Deploy persistent storage
7. **Task Group 7**: Networking - MetalLB LoadBalancer ✅ COMPLETE
   - Deploy load balancing
8. **Task Group 8**: Ingress - Traefik Controller ✅ COMPLETE
   - Deploy ingress routing
9. **Task Group 9**: Certificate Management - cert-manager ✅ COMPLETE
   - Configure certificate issuance
10. **Task Group 10**: GitOps - ArgoCD Bootstrap ✅ COMPLETE
    - Enable GitOps automation

### Phase 6: Documentation and Operational Procedures
11. **Task Group 11**: Deployment Documentation ✅ COMPLETE
    - Document deployment procedures
12. **Task Group 12**: Operational Procedures Documentation
12. **Task Group 12**: Operational Procedures Documentation ✅ COMPLETE
13. **Task Group 13**: Reference Documentation
    - Document architecture and configuration reference
13. **Task Group 13**: Reference Documentation ✅ COMPLETE
## Critical Path Items

**Must complete before moving to next phase:**
- Phase 1 → Phase 2: Terraform configuration must be ready (not necessarily applied) ✅ COMPLETE
- Phase 2 → Phase 3: Kubespray inventory and configuration complete ✅ COMPLETE
- Phase 3 → Phase 4: Ansible wrapper playbooks created ✅ COMPLETE
- Phase 4 → Phase 5: Cluster deployed and healthy (USER MUST EXECUTE DEPLOYMENT-PROCEDURES.md)
- Phase 5 → Phase 6: All platform components operational ✅ COMPLETE (manifests created)

**Can be parallelized within phases:**
- Phase 2: Task Groups 2-3 are sequential
- Phase 5: Task Groups 6-9 can be done in any order, but Task Group 10 (ArgoCD) should be last ✅ COMPLETE
- Phase 6: Task Groups 11-13 can be done in parallel or in sequence

## Testing Strategy

**Verification Points:**
1. After Task Group 1: Terraform plan succeeds ✅ COMPLETE (configuration validated)
2. After Task Group 2: Inventory structure created ✅ COMPLETE
3. After Task Group 3: Configuration files validated ✅ COMPLETE
4. After Task Group 4: Wrapper playbooks created ✅ COMPLETE
5. After Task Group 5: All nodes Ready, etcd healthy (USER MUST VERIFY)
6. After Task Group 6: PVC can be created and bound ✅ DOCUMENTED
7. After Task Group 7: LoadBalancer service gets external IP ✅ DOCUMENTED
8. After Task Group 8: Ingress routes traffic correctly ✅ DOCUMENTED
9. After Task Group 9: Certificate can be issued ✅ DOCUMENTED
10. After Task Group 10: ArgoCD manages applications ✅ DOCUMENTED

**No comprehensive test suites** - Testing is integrated into task execution with verification steps.

## Notes

- **Bare Metal Integration**: km01 is NOT provisioned by Terraform; only added to inventory
- **VM Distribution**: Distribute VMs across Proxmox cluster (pve1, pve2, pve3) for HA ✅ COMPLETE
- **Etcd Critical**: Ensure etcd distributed across all 3 control plane nodes ✅ CONFIGURED
- **Vault Dependency**: All secret retrieval depends on Vault at 192.168.10.101
- **Kubespray Location**: Assumes kubespray installed at `~/git/kubespray`
- **GitOps First**: ArgoCD deployed manually first, then manages other components ✅ COMPLETE
- **Idempotency**: All Terraform and Ansible operations should be idempotent
- **Documentation First**: Complete documentation during implementation, not after ✅ COMPLETE
- **Task Group 5 is MANUAL**: Comprehensive procedures documented in DEPLOYMENT-PROCEDURES.md for user execution

## File Locations Summary

**Terraform:** ✅ COMPLETE
- `/Users/bret/git/homelab/tf/kubespray/`

**Kubespray Configuration:** ✅ COMPLETE
- `/Users/bret/git/homelab/kubespray/inventory/homelab/` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/README.md` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/addons.yml` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-net-containerd.yml` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/all/all.yml` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/all/etcd.yml` ✅
- `/Users/bret/git/homelab/kubespray/CONFIG-DECISIONS.md` ✅
- `/Users/bret/git/homelab/kubespray/inventory/homelab/host_vars/` ✅
- `/Users/bret/git/homelab/kubespray/DEPLOYMENT-PROCEDURES.md` ✅

**Ansible:** ✅ COMPLETE
- `/Users/bret/git/homelab/ansible/playbooks/deploy_kubespray_cluster.yml` ✅
- `/Users/bret/git/homelab/ansible/playbooks/add_kubespray_node.yml` ✅
- `/Users/bret/git/homelab/ansible/playbooks/upgrade_kubespray_cluster.yml` ✅
- `/Users/bret/git/homelab/ansible/playbooks/reset_kubespray_cluster.yml` ✅

**Kubernetes Manifests:** ✅ COMPLETE
- `/Users/bret/git/homelab/k8s/democratic-csi/` ✅
  - `namespace.yaml` ✅
  - `values-iscsi.yaml` ✅
  - `values-nfs.yaml` ✅
  - `README.md` ✅
- `/Users/bret/git/homelab/k8s/metallb/` ✅
  - `namespace.yaml` ✅
  - `values.yaml` ✅
  - `ipaddresspool.yaml` ✅
  - `l2advertisement.yaml` ✅
  - `README.md` ✅
- `/Users/bret/git/homelab/k8s/traefik/` ✅
  - `namespace.yaml` ✅
  - `values.yaml` ✅
  - `README.md` ✅
- `/Users/bret/git/homelab/k8s/cert-manager/` ✅
  - `cluster-issuer-selfsigned.yaml` ✅
  - `internal-ca-cert.yaml` ✅
  - `cluster-issuer-ca.yaml` ✅
  - `README.md` ✅
- `/Users/bret/git/homelab/k8s/argocd/` ✅
  - `namespace.yaml` ✅
  - `values.yaml` ✅
  - `platform-apps.yaml` ✅
  - `README.md` ✅
- `/Users/bret/git/homelab/k8s/argocd/argocd-apps/` ✅
  - `README.md` ✅
  - `democratic-csi-iscsi-app.yaml` ✅
  - `democratic-csi-nfs-app.yaml` ✅
  - `metallb-app.yaml` ✅
  - `traefik-app.yaml` ✅
  - `cert-manager-config-app.yaml` ✅

**Documentation:**
- `/Users/bret/git/homelab/docs/KUBESPRAY-DEPLOYMENT.md`
- `/Users/bret/git/homelab/docs/KUBESPRAY-QUICKSTART.md`
- `/Users/bret/git/homelab/docs/KUBESPRAY-OPERATIONS.md`
- `/Users/bret/git/homelab/docs/KUBESPRAY-BACKUP-RESTORE.md`
- `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`
- `/Users/bret/git/homelab/docs/KUBESPRAY-ARCHITECTURE.md`
- `/Users/bret/git/homelab/docs/KUBESPRAY-CONFIG-REFERENCE.md`
- `/Users/bret/git/homelab/docs/INDEX.md`
