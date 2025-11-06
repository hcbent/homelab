# Spec Initialization: Docker Compose to ArgoCD Migration

**Date**: 2025-11-06
**Spec Path**: `/Users/bret/git/homelab/agent-os/specs/2025-11-06-docker-compose-to-argocd-migration`

## Feature Description

Migrate existing docker-compose deployments to ArgoCD Application manifests running on the newly deployed Kubernetes cluster.

**Current State:**
- Multiple applications running via docker-compose under `docker/` directory
- Production-grade Kubernetes cluster deployed via Kubespray (3 control plane + 3 worker nodes)
- ArgoCD already deployed and operational
- Democratic CSI storage backend available (iSCSI + NFS)
- MetalLB for LoadBalancer services
- Traefik for ingress/routing

**Target State:**
- All docker-compose applications converted to Kubernetes manifests or Helm charts
- Applications managed declaratively via ArgoCD
- Persistent data migrated to CSI-backed PersistentVolumes
- Proper namespace organization
- Documented migration and rollback procedures

**Scope:**
- Inventory all docker-compose files
- Create Kubernetes manifests or Helm charts for each application
- Configure ArgoCD Application resources
- Migrate persistent volumes and data
- Update networking (NodePort services as preferred pattern)
- Document procedures

**Applications to Migrate (known):**
- Media stack: Plex, Radarr, Sonarr, qBittorrent, Jackett
- Monitoring: Prometheus, Grafana (may already be in K8s)
- Home automation: Home Assistant, Pi-hole
- Infrastructure services
- LLM services: Ollama, Text Generation WebUI (may already be in K8s)

**Roadmap Context:**
This is item #3 on the product roadmap, following:
- ✅ #1: Kubespray K8s Cluster Deployment
- ✅ #2: Nginx Load Balancer for K8s API

## Next Steps

Proceed to requirements gathering phase.
