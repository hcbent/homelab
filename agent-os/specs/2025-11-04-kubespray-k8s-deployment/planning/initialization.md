# Spec Initialization: Kubespray K8s Cluster Deployment

**Date**: 2025-11-04
**Status**: Initialized

## Feature Overview

Implement automated Kubernetes cluster deployment using kubespray as an alternative to the current K3s setup. This will enable production-grade Kubernetes clusters with full customization capabilities while integrating with the existing homelab infrastructure automation pipeline.

## Initial Description

Deploy Kubernetes clusters using kubespray (already installed at ~/git/kubespray) to provide:
- Production-grade Kubernetes features and flexibility
- Full control over cluster components (CNI, storage, ingress, etc.)
- Better support for cluster upgrades and maintenance
- Integration with existing Proxmox/Terraform/Ansible infrastructure
- Coexistence or migration path from current K3s setup

## Current Infrastructure Context

**Existing Setup**:
- **Virtualization**: Proxmox hypervisor hosting all VMs
- **Infrastructure as Code**: Terraform (../tf/) provisions VMs with configurable specs
- **Configuration Management**: Ansible playbooks (../ansible/) configure hosts and K8s
- **Current K8s**: K3s cluster with:
  - Control plane: kube01-03 (3 nodes)
  - Workers: kube04-06 (3 nodes)
- **Storage**: Democratic CSI with FreeNAS iSCSI/NFS backends
- **Networking**: MetalLB for LoadBalancer, Traefik for ingress
- **GitOps**: ArgoCD manages application deployments
- **Secrets**: HashiCorp Vault integration
- **Monitoring**: Prometheus/Grafana/Elasticsearch/Kibana stack

**Kubespray Location**: ~/git/kubespray (already cloned)

## Goals

1. **Kubespray Integration**: Configure kubespray to work with homelab environment
   - Create inventory matching existing VM infrastructure
   - Customize cluster parameters for homelab use case
   - Integrate with Terraform VM provisioning

2. **Cluster Customization**: Enable configuration of:
   - CNI plugin selection (Calico, Cilium, etc.)
   - Storage integration (Democratic CSI, local storage)
   - Ingress controller setup
   - Load balancer configuration
   - Certificate management
   - Add-ons and optional components

3. **Infrastructure Integration**: Connect with existing automation
   - Ansible playbook integration or separate deployment workflow
   - Terraform output consumption for dynamic inventory
   - ArgoCD bootstrap post-deployment
   - Vault integration for secrets management

4. **Migration Strategy**: Plan for K3s coexistence or replacement
   - Parallel cluster option for testing
   - Migration path for workloads
   - Rollback considerations

5. **Documentation**: Comprehensive deployment and maintenance guides
   - Inventory configuration examples
   - Deployment procedures and runbooks
   - Upgrade and maintenance workflows
   - Troubleshooting guides

## Success Criteria

- Kubespray successfully deploys production-grade K8s clusters on Proxmox VMs
- Integration with existing Terraform/Ansible automation pipeline
- Full customization of cluster components (CNI, storage, ingress, etc.)
- Clear documentation enabling repeatable deployments
- Migration/coexistence strategy with current K3s cluster defined

## Technical Scope

**In Scope**:
- Kubespray inventory configuration for homelab nodes
- Cluster customization parameters (group_vars, host_vars)
- Deployment workflow integration with existing automation
- Post-deployment bootstrap (ArgoCD, storage, networking)
- Documentation and runbooks

**Out of Scope** (Initially):
- Actual migration of production workloads
- Replacement of existing K3s cluster (coexistence preferred initially)
- Major infrastructure changes beyond K8s deployment method
- New application deployments (focus on cluster foundation)

## Next Steps

Requirements gathering will explore:
- Desired cluster configuration options
- Integration points with existing Terraform/Ansible
- Deployment workflow preferences
- Documentation requirements
- Migration timeline and strategy
