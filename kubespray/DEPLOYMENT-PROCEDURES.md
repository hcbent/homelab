# Kubespray Cluster Deployment Procedures

## Table of Contents
1. [Pre-Deployment Checklist](#1-pre-deployment-checklist)
2. [Step 1: Provision VMs with Terraform](#2-step-1-provision-vms-with-terraform)
3. [Step 2: Deploy Cluster with Kubespray](#3-step-2-deploy-cluster-with-kubespray)
4. [Step 3: Post-Deployment Verification](#4-step-3-post-deployment-verification)
5. [Step 4: Local Kubeconfig Setup](#5-step-4-local-kubeconfig-setup)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Pre-Deployment Checklist

Before starting the deployment, verify all prerequisites are in place:

### 1.1 Vault Access

- [ ] Vault server is running and unsealed at `https://192.168.10.101:8200`
- [ ] You have a valid VAULT_TOKEN with permissions to read secrets
- [ ] Test Vault connectivity:
  ```bash
  export VAULT_ADDR="https://192.168.10.101:8200"
  export VAULT_TOKEN="your-vault-token"
  export VAULT_SKIP_VERIFY="true"

  # Test vault access
  vault status
  ```

### 1.2 Required Secrets in Vault

Verify these secrets exist in Vault:

- [ ] Proxmox credentials: `secret/homelab/proxmox/terraform`
  - Keys: `username`, `password`, `cipassword`
  ```bash
  vault kv get secret/homelab/proxmox/terraform
  ```

- [ ] FreeNAS credentials (for later Democratic CSI setup): `secret/homelab/freenas/credentials`
  - Keys: `api_key`, `password`
  ```bash
  vault kv get secret/homelab/freenas/credentials
  ```

### 1.3 SSH Configuration

- [ ] SSH key exists at `/Users/bret/.ssh/github_rsa`
- [ ] SSH key has been added to km01 bare metal node (192.168.10.234)
- [ ] Test SSH access to km01:
  ```bash
  ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234
  ```

### 1.4 Proxmox Access

- [ ] Proxmox cluster is healthy and accessible
- [ ] Template `ubuntu-25.04` exists on Proxmox
- [ ] Storage pool `tank` is available and has sufficient space (~1.6TB for 5 VMs)
- [ ] Network bridge `vmbr0` is configured
- [ ] IP addresses 192.168.10.235-239 are available (not in use)

### 1.5 DNS Configuration

- [ ] DNS server at 192.168.10.1 is operational
- [ ] Gateway at 192.168.10.1 is accessible
- [ ] Domain `lab.thewortmans.org` is configured

### 1.6 Local System Requirements

- [ ] Terraform installed (version >= 1.0)
  ```bash
  terraform version
  ```

- [ ] Ansible installed (version >= 2.12)
  ```bash
  ansible --version
  ```

- [ ] Kubespray cloned at `~/git/kubespray`
  ```bash
  ls ~/git/kubespray/cluster.yml
  ```

- [ ] Python 3 installed
  ```bash
  python3 --version
  ```

### 1.7 Configuration Files in Place

- [ ] Terraform configuration: `/Users/bret/git/homelab/tf/kubespray/`
- [ ] Kubespray inventory: `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini`
- [ ] Kubespray group_vars: `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/`
- [ ] Ansible playbooks: `/Users/bret/git/homelab/ansible/playbooks/deploy_kubespray_cluster.yml`

### 1.8 Backup Existing State (if redeploying)

If this is not your first deployment:

- [ ] Backup existing Terraform state (if any):
  ```bash
  cp /Users/bret/git/homelab/tf/kubespray/terraform.tfstate \
     /Users/bret/git/homelab/tf/kubespray/terraform.tfstate.backup-$(date +%Y%m%d-%H%M%S)
  ```

- [ ] Backup existing cluster configuration (if any):
  ```bash
  # If you have an existing cluster, backup etcd and important resources
  # See docs/KUBESPRAY-BACKUP-RESTORE.md for details
  ```

---

## 2. Step 1: Provision VMs with Terraform

This step provisions 5 VMs on Proxmox: 2 control plane nodes (km02, km03) and 3 worker nodes (kube01-kube03).

### 2.1 Navigate to Terraform Directory

```bash
\cd /Users/bret/git/homelab/tf/kubespray/
```

### 2.2 Initialize Terraform

```bash
terraform init
```

**Expected Output:**
```
Initializing the backend...
Initializing provider plugins...
- Finding latest version of telmate/proxmox...
- Finding latest version of hashicorp/vault...
...
Terraform has been successfully initialized!
```

### 2.3 Validate Configuration

```bash
terraform validate
```

**Expected Output:**
```
Success! The configuration is valid.
```

### 2.4 Review the Deployment Plan

```bash
terraform plan -var-file=terraform.tfvars
```

**Expected Output:**
- Plan shows **5 VMs to be created** (km02, km03, kube01, kube02, kube03)
- Review resource specifications:
  - Control plane VMs: 4 cores, 8GB RAM, 100GB disk
  - Worker VMs: 8 cores, 16GB RAM, 200GB disk
- Verify IP addresses: 192.168.10.235-239
- Verify Proxmox nodes: pve1, pve2, pve3 (distributed for HA)

**If plan looks correct, proceed to apply.**

### 2.5 Apply Terraform Configuration

```bash
terraform apply -var-file=terraform.tfvars
```

**You will be prompted to confirm. Type `yes` and press Enter.**

**Expected Duration:** 5-10 minutes

**Expected Output:**
```
Apply complete! Resources: 5 added, 0 changed, 0 destroyed.

Outputs:

control_plane_hostnames = [
  "km02.lab.thewortmans.org",
  "km03.lab.thewortmans.org",
]
control_plane_ips = [
  "192.168.10.235",
  "192.168.10.236",
]
worker_hostnames = [
  "kube01.lab.thewortmans.org",
  "kube02.lab.thewortmans.org",
  "kube03.lab.thewortmans.org",
]
worker_ips = [
  "192.168.10.237",
  "192.168.10.238",
  "192.168.10.239",
]
```

### 2.6 Verify VMs are Running

Check in Proxmox Web UI:
- [ ] Navigate to each Proxmox node (pve1, pve2, pve3)
- [ ] Verify VMs are running:
  - km02 (VMID 221) on pve1
  - km03 (VMID 222) on pve2
  - kube01 (VMID 223) on pve3
  - kube02 (VMID 224) on pve1
  - kube03 (VMID 225) on pve2
- [ ] Verify VMs have IP addresses assigned

Alternatively, use Terraform outputs:
```bash
terraform output
```

### 2.7 Wait for Cloud-Init Completion

VMs need time for cloud-init to complete user setup and SSH key installation.

**Wait 2-3 minutes**, then proceed to test SSH connectivity.

### 2.8 Test SSH Connectivity to All Nodes

Test each VM:

```bash
# Test km01 (bare metal)
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234 "hostname"

# Test km02
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.235 "hostname"

# Test km03
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.236 "hostname"

# Test kube01
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.237 "hostname"

# Test kube02
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.238 "hostname"

# Test kube03
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.239 "hostname"
```

**Expected Output:** Each command should return the hostname (km01, km02, km03, kube01, kube02, kube03)

### 2.9 Verify Python Installation (Required by Ansible)

```bash
for host in 192.168.10.234 192.168.10.235 192.168.10.236 192.168.10.237 192.168.10.238 192.168.10.239; do
  echo "Testing Python on $host"
  ssh -i /Users/bret/.ssh/github_rsa bret@$host "python3 --version"
done
```

**Expected Output:** Each node should report Python 3.x version

### 2.10 Verify Sudo Access

```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234 "sudo -l"
```

**Expected Output:** Should show sudo permissions without errors

**Troubleshooting:**
- If SSH fails: Check cloud-init logs on VM console, verify network configuration
- If Python missing: Cloud-init may not have completed, wait longer or manually install
- If sudo fails: Verify cloud-init user configuration

---

## 3. Step 2: Deploy Cluster with Kubespray

This step deploys Kubernetes using kubespray's Ansible playbooks.

### 3.1 Navigate to Ansible Directory

```bash
\cd /Users/bret/git/homelab/ansible
```

### 3.2 Verify Ansible Inventory

Check that inventory file is accessible:

```bash
cat /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini
```

**Verify:**
- [ ] All 6 nodes are listed (km01-km03, kube01-kube03)
- [ ] IP addresses match: 192.168.10.234-239
- [ ] Groups are correct: kube_control_plane, kube_node, etcd
- [ ] SSH user is `bret`
- [ ] SSH key path is `/Users/bret/.ssh/github_rsa`

### 3.3 Test Ansible Connectivity

```bash
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini all -m ping
```

**Expected Output:**
```
km01 | SUCCESS => { "ping": "pong" }
km02 | SUCCESS => { "ping": "pong" }
km03 | SUCCESS => { "ping": "pong" }
kube01 | SUCCESS => { "ping": "pong" }
kube02 | SUCCESS => { "ping": "pong" }
kube03 | SUCCESS => { "ping": "pong" }
```

**If any node fails, do not proceed. Fix connectivity first.**

### 3.4 Run Kubespray Deployment Playbook

```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

**Expected Duration:** 30-60 minutes (depends on network speed and system performance)

**What to Monitor:**

The playbook will run through several phases:

1. **Pre-flight Checks** (2-5 minutes)
   - Verifying Vault connectivity
   - Testing SSH to all nodes
   - Displaying deployment plan
   - **You will be prompted to press ENTER to confirm deployment**

2. **Download Phase** (5-15 minutes)
   - Downloading Kubernetes binaries
   - Downloading container images
   - Downloading CNI plugins

3. **Etcd Installation** (5-10 minutes)
   - Installing etcd on control plane nodes
   - Configuring etcd cluster
   - Verifying etcd quorum

4. **Kubernetes Control Plane** (10-20 minutes)
   - Installing kubelet, kubectl, kubeadm
   - Bootstrapping first control plane node (km01)
   - Joining additional control plane nodes (km02, km03)
   - Installing CoreDNS
   - Installing Calico CNI

5. **Worker Nodes** (5-10 minutes)
   - Installing kubelet on workers
   - Joining workers to cluster (kube01, kube02, kube03)

6. **Add-ons** (5-10 minutes)
   - Installing cert-manager
   - Installing metrics-server
   - Configuring NodeLocal DNS cache

7. **Post-deployment Verification** (2-5 minutes)
   - Checking node status
   - Checking pod status
   - Verifying etcd health

**Expected Output:**
```
PLAY RECAP *********************************************************************
km01                       : ok=XXX  changed=XXX  unreachable=0    failed=0
km02                       : ok=XXX  changed=XXX  unreachable=0    failed=0
km03                       : ok=XXX  changed=XXX  unreachable=0    failed=0
kube01                     : ok=XXX  changed=XXX  unreachable=0    failed=0
kube02                     : ok=XXX  changed=XXX  unreachable=0    failed=0
kube03                     : ok=XXX  changed=XXX  unreachable=0    failed=0

======================================
Kubespray Deployment Complete!
======================================

Next steps:
1. Copy kubeconfig from control plane:
   scp bret@km01:~/.kube/config ~/.kube/config-kubespray

2. Test cluster access:
   kubectl --kubeconfig ~/.kube/config-kubespray get nodes

3. Proceed with platform components deployment:
   - Democratic CSI for storage
   - MetalLB for load balancing
   - Traefik for ingress
   - ArgoCD for GitOps

See docs/KUBESPRAY-DEPLOYMENT.md for detailed next steps.
======================================
```

### 3.5 Common Issues During Deployment

**Issue: Playbook fails during download phase**
- **Cause:** Network connectivity issues or rate limiting
- **Solution:** Re-run the playbook. Kubespray is idempotent and will resume where it left off

**Issue: Etcd fails to form quorum**
- **Cause:** Firewall blocking etcd ports (2379, 2380) or time synchronization issues
- **Solution:** Check firewall rules, verify NTP is running on all control plane nodes

**Issue: Node fails to join cluster**
- **Cause:** Network issues, kubelet not starting, certificate problems
- **Solution:** SSH to the failing node, check kubelet logs: `sudo journalctl -u kubelet -f`

**Issue: CoreDNS pods not starting**
- **Cause:** Calico CNI not ready, node networking issues
- **Solution:** Check Calico pods: `kubectl get pods -n kube-system | grep calico`

**For more troubleshooting, see Section 6 below.**

---

## 4. Step 3: Post-Deployment Verification

After kubespray completes, verify the cluster is healthy.

### 4.1 SSH to Primary Control Plane Node (km01)

```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234
```

### 4.2 Set Up Kubeconfig Access on km01

```bash
# Create .kube directory if it doesn't exist
mkdir -p ~/.kube

# Copy admin kubeconfig
sudo cp /etc/kubernetes/admin.conf ~/.kube/config

# Set correct ownership
sudo chown bret:bret ~/.kube/config

# Set restrictive permissions
chmod 600 ~/.kube/config
```

### 4.3 Verify All Nodes are Ready

```bash
kubectl get nodes
```

**Expected Output:**
```
NAME     STATUS   ROLES           AGE   VERSION
km01     Ready    control-plane   10m   v1.29.5
km02     Ready    control-plane   8m    v1.29.5
km03     Ready    control-plane   8m    v1.29.5
kube01   Ready    <none>          5m    v1.29.5
kube02   Ready    <none>          5m    v1.29.5
kube03   Ready    <none>          5m    v1.29.5
```

**All nodes should show STATUS=Ready**

If any node is NotReady:
```bash
kubectl describe node <node-name>
```

### 4.4 Verify All System Pods are Running

```bash
kubectl get pods -A
```

**Expected Output:** All pods should be in `Running` state. Key pods to check:

- **kube-system namespace:**
  - `calico-node-*` (should have 6 pods, one per node)
  - `calico-kube-controllers-*` (1 pod)
  - `coredns-*` (2 pods)
  - `kube-apiserver-*` (3 pods, one per control plane)
  - `kube-controller-manager-*` (3 pods)
  - `kube-scheduler-*` (3 pods)
  - `kube-proxy-*` (6 pods)
  - `nodelocaldns-*` (6 pods)

- **cert-manager namespace:**
  - `cert-manager-*` (1 pod)
  - `cert-manager-cainjector-*` (1 pod)
  - `cert-manager-webhook-*` (1 pod)

**If any pods are not Running:**
```bash
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace>
```

### 4.5 Verify Etcd Cluster Health

```bash
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
```

**Expected Output:**
```
https://127.0.0.1:2379 is healthy: successfully committed proposal: took = 2.345678ms
```

### 4.6 Verify Etcd Members

```bash
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

**Expected Output:** Should show 3 members (etcd1, etcd2, etcd3) corresponding to km01, km02, km03

```
abc123..., started, etcd1, https://192.168.10.234:2380, https://192.168.10.234:2379, false
def456..., started, etcd2, https://192.168.10.235:2380, https://192.168.10.235:2379, false
ghi789..., started, etcd3, https://192.168.10.236:2380, https://192.168.10.236:2379, false
```

### 4.7 Test Cluster Functionality

Create a test deployment:

```bash
# Create test namespace
kubectl create namespace test

# Create test deployment
kubectl create deployment nginx --image=nginx --replicas=3 -n test

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=nginx -n test --timeout=120s

# Verify pods are running on different nodes
kubectl get pods -n test -o wide

# Clean up test resources
kubectl delete namespace test
```

**Expected:** 3 nginx pods should start successfully and be distributed across worker nodes

### 4.8 Label Nodes with Roles

Label nodes for clarity (optional but recommended):

```bash
# Label control plane nodes (may already be labeled by kubespray)
kubectl label node km01 node-role.kubernetes.io/control-plane="" --overwrite
kubectl label node km02 node-role.kubernetes.io/control-plane="" --overwrite
kubectl label node km03 node-role.kubernetes.io/control-plane="" --overwrite

# Label worker nodes
kubectl label node kube01 node-role.kubernetes.io/worker=""
kubectl label node kube02 node-role.kubernetes.io/worker=""
kubectl label node kube03 node-role.kubernetes.io/worker=""

# Verify labels
kubectl get nodes --show-labels
```

### 4.9 Exit km01 SSH Session

```bash
exit
```

**At this point, your cluster is deployed and healthy.**

---

## 5. Step 4: Local Kubeconfig Setup

Configure local kubectl access from your workstation.

### 5.1 Copy Kubeconfig from km01

From your local machine:

```bash
# Create backup of existing kubeconfig (if any)
cp ~/.kube/config ~/.kube/config.backup-$(date +%Y%m%d-%H%M%S) 2>/dev/null || true

# Copy kubeconfig from km01
scp -i /Users/bret/.ssh/github_rsa bret@192.168.10.234:~/.kube/config \
  ~/.kube/config-kubespray
```

### 5.2 Test Local Kubectl Access

```bash
kubectl --kubeconfig ~/.kube/config-kubespray get nodes
```

**Expected Output:** Same node list as in Step 4.3

### 5.3 Verify Cluster Info

```bash
kubectl --kubeconfig ~/.kube/config-kubespray cluster-info
```

**Expected Output:**
```
Kubernetes control plane is running at https://127.0.0.1:6443
CoreDNS is running at https://127.0.0.1:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

To further debug and diagnose cluster problems, use 'kubectl cluster-info dump'.
```

**Note:** The API server is accessed via localhost (127.0.0.1:6443) because kubespray configures a local nginx load balancer on the control plane node for HA API access.

### 5.4 Option A: Use Dedicated Kubeconfig

**Recommended for multi-cluster environments.**

Set environment variable to use kubespray kubeconfig:

```bash
export KUBECONFIG=~/.kube/config-kubespray
kubectl get nodes
```

Add to your shell profile for persistence:

```bash
# For zsh (macOS default)
echo 'export KUBECONFIG=~/.kube/config-kubespray' >> ~/.zshrc

# For bash
echo 'export KUBECONFIG=~/.kube/config-kubespray' >> ~/.bashrc
```

### 5.5 Option B: Merge into Main Kubeconfig

**Recommended if you want a single kubeconfig file.**

Merge kubespray cluster into existing kubeconfig:

```bash
# Backup existing config
cp ~/.kube/config ~/.kube/config.backup-$(date +%Y%m%d-%H%M%S)

# Merge configs
KUBECONFIG=~/.kube/config:~/.kube/config-kubespray \
  kubectl config view --flatten > ~/.kube/config-merged

# Replace main config
mv ~/.kube/config-merged ~/.kube/config

# Set correct context name
kubectl config rename-context kubernetes-admin@homelab-kubespray kubespray

# Switch to kubespray context
kubectl config use-context kubespray

# Verify
kubectl get nodes
```

### 5.6 Verify Context and Namespace

```bash
# Show current context
kubectl config current-context

# Show all contexts
kubectl config get-contexts

# Show current namespace
kubectl config view --minify | grep namespace:

# Set default namespace (optional)
kubectl config set-context --current --namespace=default
```

**Your local kubectl is now configured to access the kubespray cluster.**

---

## 6. Troubleshooting

### 6.1 Terraform Issues

**Issue: Vault authentication fails**
```
Error: Error making API request to Vault
```

**Solution:**
- Verify VAULT_ADDR and VAULT_TOKEN are set correctly
- Check Vault server is unsealed: `vault status`
- Verify token has permissions: `vault token lookup`

**Issue: Proxmox API connection fails**
```
Error: error creating Proxmox client
```

**Solution:**
- Verify Proxmox server is accessible: `ping pve1.lab.thewortmans.org`
- Check Vault secrets for Proxmox credentials
- Verify Proxmox API is responding: `curl -k https://pve1.lab.thewortmans.org:8006`

**Issue: VM creation fails - template not found**
```
Error: clone error: can't find template 'ubuntu-25.04'
```

**Solution:**
- Verify template exists in Proxmox UI
- Check template name matches exactly (case-sensitive)
- Ensure template is on the correct storage pool

**Issue: IP address already in use**
```
Error: VM IP address already assigned
```

**Solution:**
- Check if VMs from previous deployment still exist
- Destroy old VMs: `terraform destroy`
- Verify IP addresses 192.168.10.235-239 are free on network

### 6.2 SSH Connectivity Issues

**Issue: SSH connection refused**
```
ssh: connect to host 192.168.10.235 port 22: Connection refused
```

**Solution:**
- Wait longer for cloud-init to complete (2-3 minutes)
- Check VM is running in Proxmox UI
- Access VM console in Proxmox, verify SSH service: `sudo systemctl status ssh`
- Check cloud-init status: `cloud-init status`

**Issue: Permission denied (publickey)**
```
Permission denied (publickey).
```

**Solution:**
- Verify SSH key path: `/Users/bret/.ssh/github_rsa`
- Check cloud-init configured correct SSH key
- Access VM via Proxmox console, check `/home/bret/.ssh/authorized_keys`

**Issue: Host key verification failed**
```
Host key verification failed.
```

**Solution:**
- Remove old host key: `ssh-keygen -R 192.168.10.235`
- Retry SSH connection

### 6.3 Ansible Deployment Issues

**Issue: Ansible ping fails**
```
km02 | UNREACHABLE! => {"changed": false, "msg": "Failed to connect"}
```

**Solution:**
- Verify SSH connectivity manually first
- Check inventory file has correct IP addresses
- Verify ansible_ssh_private_key_file path is correct

**Issue: Playbook fails with "Python not found"**
```
fatal: [km02]: FAILED! => {"msg": "/usr/bin/python: not found"}
```

**Solution:**
- Ensure ansible_python_interpreter is set to /usr/bin/python3 in inventory
- Manually install Python on node if missing

**Issue: Kubespray download phase fails**
```
TASK [download : Download file] FAILED
```

**Solution:**
- Check internet connectivity on nodes
- Retry playbook (kubespray is idempotent)
- Consider using download_localhost: true in group_vars if consistent failures

**Issue: Etcd fails to start**
```
fatal: [km01]: FAILED! => etcd service failed to start
```

**Solution:**
- SSH to node: `ssh bret@192.168.10.234`
- Check etcd logs: `sudo journalctl -u etcd -xe`
- Common causes: Port conflicts (2379, 2380), time sync issues, firewall

**Issue: Node fails to join cluster**
```
fatal: [kube01]: FAILED! => kubelet failed to start
```

**Solution:**
- SSH to node: `ssh bret@192.168.10.237`
- Check kubelet logs: `sudo journalctl -u kubelet -xe`
- Check if API server is accessible from node
- Verify certificates are valid

### 6.4 Post-Deployment Issues

**Issue: Nodes stuck in NotReady state**
```
kube01   NotReady   <none>   5m   v1.29.5
```

**Solution:**
- Check kubelet status: `kubectl describe node kube01`
- Common cause: CNI not ready
- Check Calico pods: `kubectl get pods -n kube-system | grep calico`
- Check kubelet logs on node: `sudo journalctl -u kubelet -f`

**Issue: CoreDNS pods CrashLoopBackOff**
```
coredns-xyz   0/1   CrashLoopBackOff   5   10m
```

**Solution:**
- Check pod logs: `kubectl logs -n kube-system coredns-xyz`
- Common cause: Port conflicts, missing CNI
- Verify Calico is running: `kubectl get pods -n kube-system -l k8s-app=calico-node`

**Issue: Etcd health check fails**
```
Error: context deadline exceeded
```

**Solution:**
- Verify etcd is running: `sudo systemctl status etcd`
- Check etcd logs: `sudo journalctl -u etcd -f`
- Verify certificates are valid and paths correct
- Check firewall allows ports 2379, 2380

**Issue: Cannot access API server from local machine**
```
Unable to connect to the server: dial tcp 127.0.0.1:6443: connect: connection refused
```

**Solution:**
- This is expected - local nginx proxy only works from control plane nodes
- Update kubeconfig to use control plane IP directly:
  ```bash
  kubectl config set-cluster homelab-kubespray \
    --server=https://192.168.10.234:6443 \
    --kubeconfig ~/.kube/config-kubespray
  ```

### 6.5 Where to Find Logs

**Terraform logs:**
```bash
# Enable debug logging
export TF_LOG=DEBUG
terraform apply -var-file=terraform.tfvars
```

**Ansible logs:**
```bash
# Run with verbose output
ansible-playbook -vvv -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

**Kubespray logs on nodes:**
```bash
# Kubelet logs
sudo journalctl -u kubelet -f

# Etcd logs
sudo journalctl -u etcd -f

# Containerd logs
sudo journalctl -u containerd -f
```

**Kubernetes pod logs:**
```bash
# Specific pod
kubectl logs <pod-name> -n <namespace>

# Previous pod instance (if crashed)
kubectl logs <pod-name> -n <namespace> --previous

# All containers in pod
kubectl logs <pod-name> -n <namespace> --all-containers

# Follow logs
kubectl logs <pod-name> -n <namespace> -f
```

### 6.6 Recovery Actions

**Full redeployment (start over):**

```bash
# 1. Destroy VMs with Terraform
\cd /Users/bret/git/homelab/tf/kubespray/
terraform destroy -var-file=terraform.tfvars

# 2. Clean up km01 bare metal node
ssh bret@192.168.10.234
sudo kubeadm reset -f
sudo rm -rf /etc/kubernetes /var/lib/etcd /var/lib/kubelet /etc/cni
exit

# 3. Start over from Step 1
```

**Reset cluster without destroying VMs:**

```bash
# Use reset playbook (DESTRUCTIVE - removes all cluster data)
\cd /Users/bret/git/homelab/ansible
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/reset_kubespray_cluster.yml

# Then redeploy
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

---

## Next Steps After Successful Deployment

1. **Deploy Storage (Democratic CSI)**
   - See Task Group 6 in tasks.md
   - Install iSCSI initiator on workers
   - Deploy Democratic CSI via Helm

2. **Deploy MetalLB**
   - See Task Group 7 in tasks.md
   - Configure IP address pool
   - Deploy via Helm

3. **Deploy Traefik Ingress**
   - See Task Group 8 in tasks.md
   - Configure LoadBalancer service
   - Deploy via Helm

4. **Bootstrap ArgoCD**
   - See Task Group 10 in tasks.md
   - Deploy ArgoCD via Helm
   - Configure repository access
   - Migrate platform components to ArgoCD management

5. **Review Comprehensive Documentation**
   - `docs/KUBESPRAY-DEPLOYMENT.md` - Full deployment guide
   - `docs/KUBESPRAY-OPERATIONS.md` - Operational procedures
   - `docs/KUBESPRAY-BACKUP-RESTORE.md` - Backup and DR procedures
   - `docs/KUBESPRAY-TROUBLESHOOTING.md` - Troubleshooting guide
   - `kubespray/CONFIG-DECISIONS.md` - Configuration rationale

---

**Deployment procedures complete. Good luck with your cluster deployment!**

*Last Updated: 2025-11-04*
