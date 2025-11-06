# Nginx Load Balancer for Kubernetes HA

## Feature Description

Deploy a dedicated load balancer node for Kubernetes API server high availability. This involves:

1. Creating a Terraform module for nginx-lb VM provisioning on Proxmox
2. Implementing an Ansible playbook for nginx configuration targeting all control plane nodes (kube01, kube02, kube03)
3. Updating kubeconfig to use the load balancer endpoint instead of direct node access

## Context from the Codebase

- **Current K8s cluster**: 3 control plane nodes (kube01-03) and 3 worker nodes (kube04-06)
- **Infrastructure**: Proxmox virtualization managed via Terraform
- **Configuration management**: Ansible playbooks
- **Cluster deployment**: Recently deployed using Kubespray
- **Network**: 192.168.10.0/24 range
- **Existing Terraform modules**: Located in tf/ directory
- **Existing Ansible playbooks**: Located in ansible/ directory

## Estimated Effort

Medium (M)

## Goals

- Provide high availability for Kubernetes API server access
- Eliminate single point of failure in cluster access
- Enable seamless failover between control plane nodes
- Maintain consistent endpoint for kubectl and other API clients
