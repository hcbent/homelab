# Kubespray Cluster Troubleshooting Guide

Comprehensive troubleshooting procedures for the kubespray Kubernetes cluster covering deployment issues, networking, storage, applications, and performance.

## Table of Contents

1. [Deployment Issues](#deployment-issues)
2. [Networking Issues](#networking-issues)
3. [Storage Issues](#storage-issues)
4. [Application Issues](#application-issues)
5. [Cluster Performance](#cluster-performance)
6. [Diagnostic Commands](#diagnostic-commands)
7. [Recovery Actions](#recovery-actions)

---

## Deployment Issues

### Terraform Provisioning Failures

#### Issue: Vault Authentication Fails

**Symptoms:**
```
Error: Error making API request to Vault
URL: GET https://192.168.10.101:8200/v1/auth/token/lookup-self
Code: 403. Errors: * permission denied
```

**Diagnosis:**
```bash
# Check Vault status
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY="true"
vault status

# Check token validity
vault token lookup

# Try to read secrets
vault kv get secret/homelab/proxmox/terraform
```

**Solutions:**
1. **Token expired**: Generate new token
   ```bash
   vault login
   export VAULT_TOKEN="<new-token>"
   ```

2. **Insufficient permissions**: Verify token policy
   ```bash
   vault token lookup
   # Check policies assigned
   ```

3. **Vault sealed**: Unseal Vault
   ```bash
   vault operator unseal
   ```

---

#### Issue: Proxmox API Connection Fails

**Symptoms:**
```
Error: error creating Proxmox client: error connecting to Proxmox API
```

**Diagnosis:**
```bash
# Test network connectivity
ping pve1.lab.thewortmans.org

# Test API endpoint
curl -k https://pve1.lab.thewortmans.org:8006/api2/json/version

# Verify credentials in Vault
vault kv get secret/homelab/proxmox/terraform
```

**Solutions:**
1. **Network issue**: Check firewall, DNS resolution
2. **Wrong credentials**: Update Vault secrets
3. **API disabled**: Enable API in Proxmox
4. **Certificate issue**: Verify `skip_tls_verify = true` in provider config

---

#### Issue: Template Not Found

**Symptoms:**
```
Error: clone error: can't find template 'ubuntu-25.04'
```

**Diagnosis:**
```bash
# List templates on Proxmox
ssh root@pve1 "qm list"

# Check template exists and is marked as template
ssh root@pve1 "qm config <template-vmid>"
```

**Solutions:**
1. **Template missing**: Create template from ISO
2. **Wrong name**: Verify exact template name (case-sensitive)
3. **Wrong storage**: Ensure template on correct storage pool

---

#### Issue: IP Address Already in Use

**Symptoms:**
```
Error: VM IP address already assigned or in use
```

**Diagnosis:**
```bash
# Ping IP to check if in use
ping 192.168.10.235

# Check if old VMs exist
ssh root@pve1 "qm list | grep 192.168.10.235"

# Check Terraform state
\cd /Users/bret/git/homelab/tf/kubespray
terraform state list
```

**Solutions:**
1. **Old VMs exist**: Destroy old VMs
   ```bash
   terraform destroy -var-file=terraform.tfvars
   ```

2. **State drift**: Refresh state
   ```bash
   terraform refresh -var-file=terraform.tfvars
   ```

3. **Choose different IP**: Update terraform.tfvars

---

### SSH Connectivity Issues

#### Issue: SSH Connection Refused

**Symptoms:**
```
ssh: connect to host 192.168.10.235 port 22: Connection refused
```

**Diagnosis:**
```bash
# Check VM is running
ssh root@pve1 "qm status 221"

# Check VM console in Proxmox UI

# Check cloud-init status from console
# In VM console:
cloud-init status
```

**Solutions:**
1. **Cloud-init not complete**: Wait 2-3 minutes longer
2. **SSH service not started**:
   ```bash
   # From VM console
   sudo systemctl status ssh
   sudo systemctl start ssh
   ```

3. **Firewall blocking**: Check VM firewall rules

---

#### Issue: Permission Denied (publickey)

**Symptoms:**
```
Permission denied (publickey).
```

**Diagnosis:**
```bash
# Verify SSH key exists
ls -l /Users/bret/.ssh/github_rsa

# Check key permissions
chmod 600 /Users/bret/.ssh/github_rsa

# Check cloud-init user data from Proxmox console
# In VM:
sudo cat /var/lib/cloud/instance/user-data.txt
sudo cat /home/bret/.ssh/authorized_keys
```

**Solutions:**
1. **Wrong key**: Verify cloud-init configured with correct SSH key
2. **Key not added**: Check Terraform SSH key configuration
3. **Wrong user**: Try with correct user (bret)
   ```bash
   ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.235
   ```

---

### Ansible Deployment Issues

#### Issue: Ansible Ping Fails

**Symptoms:**
```
km02 | UNREACHABLE! => {"changed": false, "msg": "Failed to connect to the host via ssh"}
```

**Diagnosis:**
```bash
# Test SSH manually
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.235

# Check inventory file
cat /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini

# Test with verbose Ansible
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini km02 -m ping -vvv
```

**Solutions:**
1. **SSH connectivity**: Fix SSH access first
2. **Wrong IP**: Verify IPs in inventory match VMs
3. **Wrong SSH key path**: Update inventory `ansible_ssh_private_key_file`
4. **Python not found**: Install Python3 on nodes

---

#### Issue: Python Not Found

**Symptoms:**
```
fatal: [km02]: FAILED! => {"msg": "/usr/bin/python: not found"}
```

**Diagnosis:**
```bash
# Check Python on node
ssh bret@192.168.10.235 "which python3"
ssh bret@192.168.10.235 "python3 --version"
```

**Solutions:**
1. **Set Python interpreter** in inventory:
   ```ini
   [all:vars]
   ansible_python_interpreter=/usr/bin/python3
   ```

2. **Install Python**:
   ```bash
   ssh bret@192.168.10.235
   sudo apt-get update
   sudo apt-get install -y python3
   ```

---

#### Issue: Kubespray Download Phase Fails

**Symptoms:**
```
TASK [download : Download file] ******************
fatal: [km01]: FAILED! => {"msg": "Failed to download file"}
```

**Diagnosis:**
```bash
# Test internet connectivity from nodes
ssh bret@192.168.10.234 "ping -c 3 8.8.8.8"
ssh bret@192.168.10.234 "curl -I https://github.com"

# Check proxy settings
ssh bret@192.168.10.234 "env | grep -i proxy"
```

**Solutions:**
1. **Network issues**: Check internet connectivity, DNS
2. **Rate limiting**: Wait and retry (kubespray is idempotent)
3. **Use local download**: Set `download_localhost: true` in group_vars
4. **Mirror issues**: Configure alternative download mirrors

---

#### Issue: Etcd Fails to Start

**Symptoms:**
```
fatal: [km01]: FAILED! => {"msg": "etcd service failed to start"}
```

**Diagnosis:**
```bash
# SSH to node
ssh bret@192.168.10.234

# Check etcd logs
sudo journalctl -u etcd -xe

# Check etcd status
sudo systemctl status etcd

# Check ports
sudo netstat -tulpn | grep -E '2379|2380'
```

**Solutions:**
1. **Port conflict**: Check if ports 2379, 2380 in use
   ```bash
   sudo lsof -i :2379
   sudo lsof -i :2380
   ```

2. **Time sync issue**: Verify NTP
   ```bash
   sudo systemctl status systemd-timesyncd
   timedatectl
   ```

3. **Firewall blocking**: Allow etcd ports
   ```bash
   sudo ufw allow 2379/tcp
   sudo ufw allow 2380/tcp
   ```

4. **Data directory issue**: Check permissions
   ```bash
   ls -ld /var/lib/etcd
   sudo chown -R etcd:etcd /var/lib/etcd
   ```

---

#### Issue: Node Fails to Join Cluster

**Symptoms:**
```
fatal: [kube01]: FAILED! => {"msg": "kubelet failed to start"}
```

**Diagnosis:**
```bash
# SSH to failing node
ssh bret@192.168.10.237

# Check kubelet logs
sudo journalctl -u kubelet -xe

# Check kubelet status
sudo systemctl status kubelet

# Check if API server accessible
curl -k https://192.168.10.234:6443/healthz
```

**Solutions:**
1. **API server unreachable**: Check network, firewall
2. **Certificate issue**: Check certificates in `/etc/kubernetes/pki`
3. **Kubelet config**: Check `/var/lib/kubelet/config.yaml`
4. **Container runtime**: Verify containerd running
   ```bash
   sudo systemctl status containerd
   ```

---

## Networking Issues

### Pod-to-Pod Connectivity Failures

**Symptoms:**
- Pods cannot reach other pods
- `ping` from one pod to another fails

**Diagnosis:**
```bash
# Check Calico pods
kubectl get pods -n kube-system | grep calico

# Check Calico node status
kubectl get nodes -o wide

# Test pod-to-pod connectivity
kubectl run test1 --image=nicolaka/netshoot --rm -it -- /bin/bash
# In pod:
ping <another-pod-ip>
```

**Solutions:**
1. **Calico not running**: Check Calico pods
   ```bash
   kubectl logs -n kube-system <calico-node-pod>
   ```

2. **IP forwarding disabled**:
   ```bash
   ssh bret@kube01
   sudo sysctl net.ipv4.ip_forward
   # Should be 1
   ```

3. **Firewall blocking**: Check node firewalls

---

### Service ClusterIP Not Accessible

**Symptoms:**
- Cannot access service via ClusterIP
- `curl` to service IP times out

**Diagnosis:**
```bash
# Check service
kubectl get svc -A

# Check endpoints
kubectl get endpoints -A

# Check kube-proxy
kubectl get pods -n kube-system | grep kube-proxy
kubectl logs -n kube-system <kube-proxy-pod>

# Check iptables rules
ssh bret@kube01
sudo iptables -t nat -L -n -v | grep <service-ip>
```

**Solutions:**
1. **No endpoints**: Check pod selector matches pods
   ```bash
   kubectl describe svc <service-name>
   kubectl get pods -l <selector>
   ```

2. **Kube-proxy issue**: Restart kube-proxy
   ```bash
   kubectl delete pod -n kube-system -l k8s-app=kube-proxy
   ```

---

### Ingress Not Routing Traffic

**Symptoms:**
- External traffic not reaching services
- Ingress returns 404 or connection refused

**Diagnosis:**
```bash
# Check Traefik pods
kubectl get pods -n traefik

# Check Traefik service
kubectl get svc -n traefik

# Check Ingress resources
kubectl get ingress -A

# Check Traefik logs
kubectl logs -n traefik <traefik-pod>
```

**Solutions:**
1. **Traefik not running**: Check pod status
2. **No LoadBalancer IP**: Check MetalLB
3. **Ingress misconfigured**: Verify Ingress spec
   ```bash
   kubectl describe ingress <ingress-name>
   ```

---

### MetalLB Not Assigning IPs

**Symptoms:**
- LoadBalancer services stuck in `<pending>` state
- No external IP assigned

**Diagnosis:**
```bash
# Check MetalLB pods
kubectl get pods -n metallb-system

# Check MetalLB speaker logs
kubectl logs -n metallb-system -l component=speaker

# Check IPAddressPool
kubectl get ipaddresspool -n metallb-system

# Check L2Advertisement
kubectl get l2advertisement -n metallb-system
```

**Solutions:**
1. **MetalLB not running**: Check pod status
2. **No IP pool**: Create IPAddressPool
3. **IP pool exhausted**: Expand IP range
4. **ARP not working**: Check `kube_proxy_strict_arp: true` in kubespray config

---

### DNS Resolution Failures

**Symptoms:**
- Pods cannot resolve DNS names
- `nslookup kubernetes.default` fails

**Diagnosis:**
```bash
# Check CoreDNS pods
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Check CoreDNS logs
kubectl logs -n kube-system <coredns-pod>

# Check NodeLocal DNS
kubectl get pods -n kube-system -l k8s-app=nodelocaldns

# Test DNS from pod
kubectl run test --image=busybox --rm -it -- nslookup kubernetes.default
```

**Solutions:**
1. **CoreDNS not running**: Check pod status, restart if needed
2. **NodeLocal DNS issue**: Check nodelocaldns pods
3. **Upstream DNS unreachable**: Check upstream DNS (192.168.10.1)
   ```bash
   ssh bret@kube01
   ping 192.168.10.1
   ```

---

## Storage Issues

### PVC Stuck in Pending State

**Symptoms:**
- PVC status: `Pending`
- Pod cannot start due to volume mount failure

**Diagnosis:**
```bash
# Check PVC
kubectl describe pvc <pvc-name>

# Check storage class
kubectl get storageclass

# Check CSI pods
kubectl get pods -n democratic-csi

# Check CSI driver logs
kubectl logs -n democratic-csi <csi-controller-pod>
```

**Solutions:**
1. **No storage class**: Create storage class
2. **CSI driver not running**: Check democratic-csi pods
3. **FreeNAS unreachable**: Test connectivity
   ```bash
   ping <freenas-ip>
   ```

4. **Quota exceeded**: Check FreeNAS storage pool usage

---

### Democratic CSI Pod Errors

**Symptoms:**
- CSI pods CrashLoopBackOff
- Volume provisioning fails

**Diagnosis:**
```bash
# Check CSI pods
kubectl get pods -n democratic-csi

# Check controller logs
kubectl logs -n democratic-csi <democratic-csi-controller-pod>

# Check node logs
kubectl logs -n democratic-csi <democratic-csi-node-pod>

# Check CSI driver
kubectl get csidrivers
```

**Solutions:**
1. **API authentication failure**: Check FreeNAS credentials in secret
2. **iSCSI not installed**: Install on worker nodes
   ```bash
   ssh bret@kube01
   sudo apt-get install -y open-iscsi
   sudo systemctl enable --now iscsid
   ```

3. **FreeNAS API error**: Check FreeNAS logs

---

### iSCSI Connection Failures

**Symptoms:**
- Pods cannot mount iSCSI volumes
- Volume attach errors

**Diagnosis:**
```bash
# Check iSCSI service on node
ssh bret@kube01
sudo systemctl status iscsid

# Check iSCSI sessions
sudo iscsiadm -m session

# Check dmesg for iSCSI errors
sudo dmesg | grep -i iscsi
```

**Solutions:**
1. **iSCSI service not running**: Start iscsid
   ```bash
   sudo systemctl start iscsid
   ```

2. **Network issue**: Test connectivity to FreeNAS iSCSI portal
3. **Wrong credentials**: Verify CHAP authentication (if configured)

---

### Volume Mount Failures

**Symptoms:**
- Pod stuck in `ContainerCreating`
- Mount errors in events

**Diagnosis:**
```bash
# Check pod events
kubectl describe pod <pod-name>

# Check node logs
ssh bret@kube01
sudo journalctl -u kubelet | grep -i mount

# Check mounted volumes
df -h
mount | grep /var/lib/kubelet
```

**Solutions:**
1. **Permission issue**: Check volume permissions
2. **Stale mount**: Unmount stale volume
   ```bash
   sudo umount /var/lib/kubelet/pods/<pod-uid>/volumes/...
   ```

3. **Node reboot needed**: Restart node (after draining)

---

## Application Issues

### Pods Stuck in Pending

**Symptoms:**
- Pod status: `Pending`
- Pod not scheduled to any node

**Diagnosis:**
```bash
# Describe pod to see scheduling errors
kubectl describe pod <pod-name>

# Check node resources
kubectl top nodes

# Check taints/tolerations
kubectl describe nodes | grep -A 5 Taints
```

**Solutions:**
1. **Insufficient resources**: Add more nodes or reduce resource requests
2. **Node selector mismatch**: Fix node selector in pod spec
3. **Taints**: Add tolerations to pod spec
4. **PVC pending**: Fix storage issue first

---

### Pods in CrashLoopBackOff

**Symptoms:**
- Pod status: `CrashLoopBackOff`
- Container keeps restarting

**Diagnosis:**
```bash
# Check pod logs
kubectl logs <pod-name>
kubectl logs <pod-name> --previous

# Check pod events
kubectl describe pod <pod-name>

# Check liveness/readiness probes
kubectl get pod <pod-name> -o yaml | grep -A 10 Probe
```

**Solutions:**
1. **Application error**: Fix application code
2. **Missing dependencies**: Check configmaps, secrets
3. **Wrong probes**: Adjust liveness/readiness probe settings
4. **Resource limits**: Increase memory/CPU limits

---

### ImagePullBackOff Errors

**Symptoms:**
- Pod status: `ImagePullBackOff` or `ErrImagePull`

**Diagnosis:**
```bash
# Check pod events
kubectl describe pod <pod-name>

# Check image name
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'

# Test image pull manually on node
ssh bret@kube01
sudo crictl pull <image-name>
```

**Solutions:**
1. **Wrong image name**: Fix image name in deployment
2. **Private registry**: Add image pull secret
3. **Network issue**: Check internet connectivity
4. **Registry down**: Use different registry or mirror

---

### ArgoCD Sync Failures

**Symptoms:**
- ArgoCD application stuck in `OutOfSync` or `Degraded`

**Diagnosis:**
```bash
# Check application status
kubectl get applications -n argocd

# Describe application
kubectl describe application -n argocd <app-name>

# Check ArgoCD logs
kubectl logs -n argocd <argocd-application-controller-pod>
```

**Solutions:**
1. **Git repo unreachable**: Check repo credentials
2. **Manifest errors**: Fix YAML syntax
3. **Resource conflicts**: Manually delete conflicting resources
4. **Sync hook failure**: Check sync hooks in logs

---

### Certificate Issuance Failures

**Symptoms:**
- Certificate stuck in `Pending`
- TLS not working

**Diagnosis:**
```bash
# Check certificate
kubectl describe certificate <cert-name>

# Check cert-manager pods
kubectl get pods -n cert-manager

# Check cert-manager logs
kubectl logs -n cert-manager <cert-manager-pod>

# Check ClusterIssuer
kubectl describe clusterissuer <issuer-name>
```

**Solutions:**
1. **Issuer misconfigured**: Fix ClusterIssuer
2. **Cert-manager not running**: Check pod status
3. **DNS validation fails**: Check DNS records (if using DNS-01)
4. **Rate limit**: Wait and retry (Let's Encrypt rate limits)

---

## Cluster Performance

### High CPU/Memory on Control Plane

**Symptoms:**
- Control plane nodes using >90% CPU or memory
- API server slow to respond

**Diagnosis:**
```bash
# Check resource usage
kubectl top nodes

# Check control plane pods
kubectl top pods -n kube-system

# Check API server logs
ssh bret@192.168.10.234
sudo journalctl -u kube-apiserver | tail -100

# Check etcd performance
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint status --write-out=table
```

**Solutions:**
1. **Too many API requests**: Investigate clients
2. **Etcd database large**: Compact etcd (see KUBESPRAY-OPERATIONS.md)
3. **Insufficient resources**: Add CPU/memory to control plane nodes
4. **Too many objects**: Clean up unused resources

---

### Etcd Performance Issues

**Symptoms:**
- Slow cluster operations
- Etcd latency warnings in logs

**Diagnosis:**
```bash
ssh bret@192.168.10.234

# Check etcd metrics
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint status --write-out=table

# Check database size
sudo du -sh /var/lib/etcd

# Check disk latency
sudo fio --name=random-write --ioengine=posixaio --rw=randwrite --bs=4k --size=4g --numjobs=1 --iodepth=1 --runtime=60 --time_based --end_fsync=1
```

**Solutions:**
1. **Large database**: Compact and defragment (see KUBESPRAY-OPERATIONS.md)
2. **Slow disk**: Use faster storage (SSD)
3. **High network latency**: Check network between etcd members
4. **Too many revisions**: Reduce retention

---

### API Server Slow Responses

**Symptoms:**
- `kubectl` commands slow
- API timeouts

**Diagnosis:**
```bash
# Check API server logs
ssh bret@192.168.10.234
sudo journalctl -u kube-apiserver | grep -i latency

# Check API server resource usage
kubectl top pod -n kube-system kube-apiserver-km01

# Test API latency
time kubectl get nodes
```

**Solutions:**
1. **Etcd slow**: Fix etcd performance
2. **Too many requests**: Rate limit clients
3. **Large responses**: Paginate large list requests
4. **Insufficient resources**: Scale control plane

---

### Scheduler Delays

**Symptoms:**
- Pods take long time to schedule
- Pods stuck in `Pending` longer than expected

**Diagnosis:**
```bash
# Check scheduler logs
kubectl logs -n kube-system <kube-scheduler-pod>

# Check scheduler events
kubectl get events -A | grep scheduler

# Check node resources
kubectl top nodes
```

**Solutions:**
1. **No available nodes**: Add more nodes
2. **Resource fragmentation**: Consolidate workloads
3. **Too many pending pods**: Batch pod creation
4. **Scheduler misconfigured**: Check scheduler config

---

## Diagnostic Commands

### Essential Troubleshooting Commands

**Cluster-wide:**
```bash
# Node status
kubectl get nodes -o wide

# All pods
kubectl get pods -A -o wide

# All resources
kubectl get all -A

# Cluster info
kubectl cluster-info
kubectl cluster-info dump > cluster-dump.txt

# Component status (deprecated but still useful)
kubectl get componentstatuses
```

**Pod-level:**
```bash
# Pod logs
kubectl logs <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace> --previous
kubectl logs <pod-name> -n <namespace> -c <container-name>

# Pod description
kubectl describe pod <pod-name> -n <namespace>

# Pod events
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Execute in pod
kubectl exec -it <pod-name> -n <namespace> -- /bin/bash
```

**Node-level:**
```bash
# Node description
kubectl describe node <node-name>

# Node logs (SSH to node)
ssh bret@<node-ip>
sudo journalctl -u kubelet -f
sudo journalctl -u containerd -f
sudo journalctl -u etcd -f

# Resource usage
kubectl top nodes
kubectl top pods -A
```

**Network debugging:**
```bash
# Create debug pod
kubectl run netshoot --image=nicolaka/netshoot --rm -it -- /bin/bash

# In pod:
ping <ip>
nslookup <hostname>
curl <url>
traceroute <ip>
```

---

## Recovery Actions

### Restart Pods

```bash
# Delete pod (will be recreated)
kubectl delete pod <pod-name> -n <namespace>

# Restart deployment
kubectl rollout restart deployment <deployment-name> -n <namespace>

# Scale deployment to 0 and back
kubectl scale deployment <deployment-name> --replicas=0 -n <namespace>
kubectl scale deployment <deployment-name> --replicas=3 -n <namespace>
```

### Restart Node Services

```bash
ssh bret@<node-ip>

# Restart kubelet
sudo systemctl restart kubelet

# Restart containerd
sudo systemctl restart containerd

# Restart etcd (control plane only)
sudo systemctl restart etcd
```

### Reset Node

**WARNING: This removes the node from the cluster**

```bash
# Drain node
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# SSH to node
ssh bret@<node-ip>

# Reset node
sudo kubeadm reset -f
sudo rm -rf /etc/kubernetes /var/lib/kubelet /var/lib/etcd /etc/cni

# Reboot
sudo reboot
```

Then re-add node using `add_kubespray_node.yml` playbook.

### Full Cluster Reset

**WARNING: This destroys the entire cluster**

```bash
# Use reset playbook
\cd /Users/bret/git/homelab/ansible
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/reset_kubespray_cluster.yml

# Then redeploy
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

---

## When to Engage Support

Escalate to upstream support if:
1. Kubespray bug suspected: https://github.com/kubernetes-sigs/kubespray/issues
2. Kubernetes bug: https://github.com/kubernetes/kubernetes/issues
3. Component bug: Report to component maintainers (Calico, Democratic CSI, etc.)

---

## Related Documentation

- **Deployment**: `docs/KUBESPRAY-DEPLOYMENT.md`
- **Operations**: `docs/KUBESPRAY-OPERATIONS.md`
- **Backup/Restore**: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Architecture**: `docs/KUBESPRAY-ARCHITECTURE.md`

---

*Last Updated: 2025-11-04*
