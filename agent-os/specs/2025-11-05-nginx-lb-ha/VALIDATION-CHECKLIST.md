# Nginx Load Balancer HA - Validation Checklist

This checklist validates that the nginx load balancer HA cluster is properly deployed and ready for production use.

## Pre-Deployment Validation

### Infrastructure Layer

- [ ] **Terraform Configuration**
  - [ ] Terraform validate passes without errors
  - [ ] Both VMs defined in terraform.tfvars (nginx-lb01, nginx-lb02)
  - [ ] VMIDs assigned correctly (250, 251)
  - [ ] IP addresses configured (192.168.10.251, 192.168.10.252)
  - [ ] Anti-affinity: VMs on different Proxmox hosts (pve1, pve2)
  - [ ] Storage backend set to "tank"
  - [ ] VM tags: "nginx;loadbalancer;ha"
  - [ ] Cloud-init configuration references correct SSH keys

- [ ] **VM Provisioning**
  - [ ] Terraform apply completed successfully
  - [ ] nginx-lb01 accessible via SSH (192.168.10.251)
  - [ ] nginx-lb02 accessible via SSH (192.168.10.252)
  - [ ] VMs running on correct Proxmox hosts
  - [ ] System updates applied during provisioning

### Ansible Configuration

- [ ] **Inventory Configuration**
  - [ ] nginx_lb group created in inventory/lab
  - [ ] Both hosts present in nginx_lb group
  - [ ] ansible_host variables correct (251, 252)
  - [ ] Group variables file exists (group_vars/nginx_lb.yml)
  - [ ] cluster_vip variable set to 192.168.10.250
  - [ ] cluster_name variable set to nginx-lb-cluster
  - [ ] k8s_control_plane nodes defined with correct IPs
  - [ ] k8s_workers nodes defined with correct IPs
  - [ ] Ansible ping succeeds to both nodes

- [ ] **Playbook Execution**
  - [ ] Playbook runs without errors on nginx-lb01
  - [ ] Playbook runs without errors on nginx-lb02
  - [ ] Playbook is idempotent (no changes on re-run)

## Post-Deployment Validation

### Nginx Configuration

- [ ] **Service Status**
  - [ ] Nginx installed on nginx-lb01
  - [ ] Nginx installed on nginx-lb02
  - [ ] Nginx service running on nginx-lb01
  - [ ] Nginx service running on nginx-lb02
  - [ ] Nginx service enabled (starts on boot)

- [ ] **Configuration Validation**
  - [ ] Nginx configuration syntax valid (nginx -t passes)
  - [ ] Stream block exists for K8s API (port 6443)
  - [ ] HTTP blocks exist for NodePort services
  - [ ] Upstream blocks configured for control plane nodes
  - [ ] Upstream blocks configured for worker nodes
  - [ ] Health check endpoint accessible (port 8888)
  - [ ] Configuration identical on both nodes

- [ ] **Stream Configuration (K8s API)**
  - [ ] Listening on port 6443
  - [ ] Upstream includes all 3 control plane nodes
  - [ ] Health checks configured (max_fails=2, fail_timeout=30s)
  - [ ] Load balancing algorithm set to least_conn
  - [ ] Proxy timeouts configured (proxy_timeout=10m)

- [ ] **HTTP Configuration (NodePort Services)**
  - [ ] ArgoCD HTTP listening on port 8080
  - [ ] ArgoCD HTTPS listening on port 8443
  - [ ] Traefik HTTP listening on port 80
  - [ ] Traefik HTTPS listening on port 443
  - [ ] WebSocket support configured
  - [ ] Proxy headers configured correctly
  - [ ] Health checks configured for worker nodes

### HA Cluster Configuration

- [ ] **Corosync**
  - [ ] Corosync installed on both nodes
  - [ ] Corosync service running on nginx-lb01
  - [ ] Corosync service running on nginx-lb02
  - [ ] Corosync configuration deployed (/etc/corosync/corosync.conf)
  - [ ] Two-node quorum policy configured (two_node: 1)
  - [ ] Cluster name set to nginx-lb-cluster
  - [ ] Both nodes in corosync membership
  - [ ] Corosync ring status healthy

- [ ] **Pacemaker**
  - [ ] Pacemaker installed on both nodes
  - [ ] Pacemaker service running on nginx-lb01
  - [ ] Pacemaker service running on nginx-lb02
  - [ ] Pacemaker service enabled on both nodes
  - [ ] STONITH disabled (as expected for homelab)

- [ ] **Cluster Status**
  - [ ] Cluster shows 2 nodes online (crm status)
  - [ ] No errors in cluster status
  - [ ] No warnings in cluster status (acceptable warnings documented)
  - [ ] Cluster quorum achieved

- [ ] **VIP Configuration**
  - [ ] VIP resource configured (cluster-vip)
  - [ ] VIP address is 192.168.10.250
  - [ ] VIP resource running/started
  - [ ] VIP initially on nginx-lb01 (preferred primary)
  - [ ] Location constraint configured (nginx-lb01 preferred)
  - [ ] Resource stickiness configured
  - [ ] VIP responds to ping
  - [ ] VIP accessible from cluster nodes
  - [ ] VIP accessible from local workstation

### Kubernetes API Integration

- [ ] **API Server Connectivity**
  - [ ] K8s API accessible through VIP (curl -k https://192.168.10.250:6443)
  - [ ] All 3 control plane backends accessible
  - [ ] Backend health checks functional
  - [ ] Traffic distributes across control plane nodes

- [ ] **Kubeconfig Updates**
  - [ ] Kubeconfig backup created on remote nodes
  - [ ] Kubeconfig updated on km01 (control plane)
  - [ ] Kubeconfig updated on km02 (control plane)
  - [ ] Kubeconfig updated on km03 (control plane)
  - [ ] Kubeconfig updated on kube01 (worker)
  - [ ] Kubeconfig updated on kube02 (worker)
  - [ ] Kubeconfig updated on kube03 (worker)
  - [ ] Local workstation kubeconfig updated (manual)
  - [ ] Server endpoint is https://192.168.10.250:6443

- [ ] **kubectl Operations**
  - [ ] kubectl cluster-info works through VIP
  - [ ] kubectl get nodes works through VIP
  - [ ] kubectl get pods --all-namespaces works
  - [ ] kubectl apply/delete operations work
  - [ ] kubectl watch commands work (kubectl get pods -w)
  - [ ] Long-running kubectl commands don't timeout
  - [ ] Certificate authentication works through LB
  - [ ] No TLS/certificate validation errors

### NodePort Services Integration

- [ ] **ArgoCD**
  - [ ] ArgoCD deployed in cluster
  - [ ] ArgoCD HTTP accessible through VIP (port 8080)
  - [ ] ArgoCD HTTPS accessible through VIP (port 8443)
  - [ ] ArgoCD UI loads correctly
  - [ ] ArgoCD login works
  - [ ] ArgoCD traffic balanced across workers

- [ ] **Traefik**
  - [ ] Traefik deployed in cluster
  - [ ] Traefik HTTP accessible through VIP (port 80)
  - [ ] Traefik HTTPS accessible through VIP (port 443)
  - [ ] Traefik dashboard accessible
  - [ ] Traefik routes traffic correctly
  - [ ] Traefik traffic balanced across workers

- [ ] **WebSocket Support**
  - [ ] WebSocket connections establish successfully
  - [ ] WebSocket upgrade headers present
  - [ ] Long-lived WebSocket connections maintained

## Functional Testing

### HA Failover Tests

- [ ] **Primary Node Failure**
  - [ ] VIP moves to nginx-lb02 when nginx-lb01 stops
  - [ ] Failover completes in < 30 seconds
  - [ ] kubectl operations continue during failover
  - [ ] NodePort services remain accessible
  - [ ] Max 2-3 transient errors during failover
  - [ ] No permanent service disruption

- [ ] **Primary Node Recovery (Failback)**
  - [ ] VIP returns to nginx-lb01 when node recovers
  - [ ] Failback completes in < 30 seconds
  - [ ] Automatic failback configured (preferred primary)
  - [ ] kubectl operations continue during failback
  - [ ] NodePort services remain accessible
  - [ ] No permanent service disruption

- [ ] **Backend Node Failures**
  - [ ] Nginx detects failed control plane node
  - [ ] Traffic routes to healthy control plane nodes
  - [ ] Health check timeout respected (30s)
  - [ ] Failed node automatically returns to pool
  - [ ] Nginx detects failed worker node
  - [ ] NodePort traffic routes to healthy workers

- [ ] **Long-Running Operations**
  - [ ] kubectl watch survives failover
  - [ ] kubectl logs -f doesn't break during failover
  - [ ] Continuous kubectl operations maintain connection
  - [ ] WebSocket connections maintained during failover

### Load Balancing Tests

- [ ] **K8s API Load Balancing**
  - [ ] Connections distribute across all 3 control plane nodes
  - [ ] least_conn algorithm working correctly
  - [ ] No single node overwhelmed
  - [ ] Connection counts balanced

- [ ] **NodePort Load Balancing**
  - [ ] HTTP requests distribute across all 3 worker nodes
  - [ ] least_conn algorithm working for NodePort
  - [ ] Response times consistent across backends
  - [ ] No single worker overwhelmed

### End-to-End Workflows

- [ ] **Application Deployment**
  - [ ] Can deploy application via kubectl through VIP
  - [ ] Application pods start successfully
  - [ ] NodePort service created successfully
  - [ ] NodePort accessible through load balancer
  - [ ] Can access application UI through VIP

- [ ] **Application Management**
  - [ ] Can scale deployment through VIP
  - [ ] Can view logs through VIP
  - [ ] Can execute commands in pods through VIP
  - [ ] Can delete resources through VIP

### Stress Testing

- [ ] **High Connection Count**
  - [ ] Load balancer handles 100+ concurrent kubectl connections
  - [ ] No connection refused errors
  - [ ] Response times remain acceptable
  - [ ] System resources within limits

- [ ] **Rapid Failover**
  - [ ] Multiple failover/failback cycles successful
  - [ ] No cluster instability
  - [ ] No configuration corruption
  - [ ] VIP consistently returns to primary

## Operational Validation

### Monitoring and Logging

- [ ] **Log Files**
  - [ ] Nginx access logs present and rotating
  - [ ] Nginx error logs present and rotating
  - [ ] Corosync logs accessible via journalctl
  - [ ] Pacemaker logs accessible via journalctl
  - [ ] Log retention policy configured

- [ ] **Health Check Endpoints**
  - [ ] Nginx health endpoint accessible (port 8888)
  - [ ] Health endpoint returns correct status
  - [ ] Health checks can be monitored externally

- [ ] **Monitoring Integration**
  - [ ] Prometheus can scrape nginx metrics (if configured)
  - [ ] Cluster status exportable to monitoring
  - [ ] Alerts configured for critical events
  - [ ] Grafana dashboards available (if configured)

### Documentation

- [ ] **Deployment Documentation**
  - [ ] Deployment guide complete and accurate
  - [ ] Architecture documented
  - [ ] Configuration parameters documented
  - [ ] IP addresses and ports documented

- [ ] **Operational Documentation**
  - [ ] Operational procedures documented
  - [ ] Troubleshooting guide available
  - [ ] Common commands documented
  - [ ] Disaster recovery procedures documented

- [ ] **Maintenance Documentation**
  - [ ] Planned maintenance procedures documented
  - [ ] Configuration update procedures documented
  - [ ] Adding new services documented
  - [ ] Backup and restore procedures documented

### Configuration Management

- [ ] **Version Control**
  - [ ] All configuration in Git
  - [ ] Terraform code committed
  - [ ] Ansible playbooks committed
  - [ ] Templates committed
  - [ ] Documentation committed

- [ ] **Idempotency**
  - [ ] Ansible playbook can be re-run safely
  - [ ] No errors on playbook re-run
  - [ ] Configuration remains consistent
  - [ ] No unexpected changes

- [ ] **Backup**
  - [ ] Nginx configuration backed up
  - [ ] Corosync configuration backed up
  - [ ] Pacemaker configuration backed up
  - [ ] VM snapshots created in Proxmox

## Security Validation

### Network Security

- [ ] **Firewall Rules**
  - [ ] Only required ports open
  - [ ] Corosync ports secured (internal only)
  - [ ] Nginx ports accessible as needed
  - [ ] No unnecessary services exposed

- [ ] **TLS/SSL**
  - [ ] TLS passthrough working for K8s API
  - [ ] Certificate validation end-to-end
  - [ ] No certificate errors
  - [ ] HTTPS NodePort services working

### Access Control

- [ ] **SSH Access**
  - [ ] Key-based authentication only
  - [ ] No password authentication
  - [ ] Correct user permissions
  - [ ] Sudo access configured correctly

- [ ] **Service Access**
  - [ ] kubectl requires valid certificates
  - [ ] No anonymous access to services
  - [ ] RBAC enforced through load balancer

## Performance Validation

### Response Times

- [ ] **K8s API Response Times**
  - [ ] kubectl get nodes < 1 second
  - [ ] kubectl get pods < 2 seconds
  - [ ] kubectl apply < 3 seconds
  - [ ] No significant latency introduced

- [ ] **NodePort Response Times**
  - [ ] HTTP requests < 500ms
  - [ ] HTTPS requests < 500ms
  - [ ] WebSocket connections < 200ms
  - [ ] Acceptable latency for UI interactions

### Resource Usage

- [ ] **nginx-lb01 Resources**
  - [ ] CPU usage < 50% under normal load
  - [ ] Memory usage < 50% of 2GB
  - [ ] Disk usage < 50% of 20GB
  - [ ] Network throughput acceptable

- [ ] **nginx-lb02 Resources**
  - [ ] CPU usage < 50% under normal load
  - [ ] Memory usage < 50% of 2GB
  - [ ] Disk usage < 50% of 20GB
  - [ ] Network throughput acceptable

## Production Readiness

### Acceptance Criteria

- [ ] **Critical Requirements Met**
  - [ ] HA cluster operational with 2 nodes
  - [ ] VIP accessible and responds
  - [ ] Automatic failover works (< 30 seconds)
  - [ ] Automatic failback works (< 30 seconds)
  - [ ] kubectl works through VIP
  - [ ] NodePort services accessible through VIP
  - [ ] No service disruption during failover
  - [ ] Backend health checks functional

- [ ] **Operational Requirements Met**
  - [ ] Comprehensive documentation complete
  - [ ] Troubleshooting procedures validated
  - [ ] Monitoring integration planned
  - [ ] Backup procedures validated
  - [ ] Disaster recovery procedures validated

- [ ] **Quality Requirements Met**
  - [ ] All tests pass (infrastructure, configuration, functional)
  - [ ] Configuration is idempotent
  - [ ] No known critical bugs
  - [ ] Performance acceptable
  - [ ] Security requirements met

### Sign-Off

- [ ] **Technical Review**
  - [ ] Infrastructure team reviewed and approved
  - [ ] All test results documented
  - [ ] Known issues documented with workarounds
  - [ ] Runbook validated

- [ ] **Production Deployment**
  - [ ] Deployment schedule confirmed
  - [ ] Rollback plan documented and validated
  - [ ] Monitoring alerts configured
  - [ ] Team trained on operations

---

## Test Execution Summary

**Date:** _______________

**Executed By:** _______________

**Test Results:**
- Total Checks: _____
- Passed: _____
- Failed: _____
- Skipped: _____

**Critical Issues:**
(List any critical issues found)

**Known Limitations:**
(List any known limitations)

**Production Readiness Assessment:**
- [ ] Ready for production
- [ ] Needs minor fixes
- [ ] Needs major work

**Approvals:**
- Infrastructure Lead: _______________ Date: _______________
- Operations Lead: _______________ Date: _______________
- Security Lead: _______________ Date: _______________

---

**Document Version:** 1.0
**Last Updated:** 2025-11-06
**Next Review Date:** _______________
