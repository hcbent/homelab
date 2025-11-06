# Spec Requirements: Docker Compose to ArgoCD Migration

## Initial Description

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

## Requirements Discussion

### First Round Questions

**Q1:** For application inventory - should I scan the `docker/` directory to identify all docker-compose files, or do you have a preferred list of applications to migrate first?

**Answer:** Scan the `docker/` directory to identify all applications requiring migration.

**Q2:** For storage strategy - I'm assuming we'll use iSCSI (RWO) for application databases/configs and NFS (RWX) for shared media libraries. Is that the right approach for your use case?

**Answer:**
- Use iSCSI/RWO for application databases and config (when single-writer)
- Use NFS/RWX for shared media libraries accessed by multiple services
- Media files are already on Synology Diskstation shared over NFS (visible in current docker-compose files)

**Q3:** For service exposure - since you prefer NodePort services, should we configure all migrated applications as NodePort type (not LoadBalancer or Ingress)? This would allow your NGINX Proxy Manager + Unifi router to handle external routing.

**Answer:** Yes, expose all services as NodePort. NGINX Proxy Manager routing configuration is OUT OF SCOPE for this spec - just document that services will be exposed as NodePort.

**Q4:** For ArgoCD application organization - should we use Helm charts where available (e.g., official Plex, Sonarr charts) or create custom Kubernetes manifests? I'm thinking Helm charts with custom values files following the multi-source pattern you're already using.

**Answer:** Use Helm charts whenever possible, following the multi-source pattern (remote Helm chart + local values repository).

**Q5:** For namespace organization - should we group related services (e.g., `media` namespace for Plex/Radarr/Sonarr/qBittorrent/Jackett, `infrastructure` for Pi-hole) or keep each in its own namespace?

**Answer:** Group related services where it makes sense. Examples:
- `media` namespace for Plex/Radarr/Sonarr/qBittorrent/Jackett
- `infrastructure` for Pi-hole and similar services

**Q6:** For migration sequence - I'm thinking we should migrate non-critical services first to test the pattern, then infrastructure services, and finally the media stack (most complex with most data). Should we also include a rollback strategy in case services need to revert to docker-compose temporarily?

**Answer:** Yes to migration sequence (non-critical → infrastructure → media stack). Yes to rollback strategy - keep docker-compose files in place during migration and document cutover procedure with rollback steps for each service. Mark `docker/` directory as "legacy" once K8s deployments are validated.

**Q7:** For data migration - should we create Ansible playbooks to automate copying persistent volumes from docker hosts to Kubernetes PVCs, or handle this manually per service?

**Answer:** Manual procedure preferred - user wants to handle moving configs & metadata themselves. Create documented procedures, not automated Ansible playbooks for data migration.

**Q8:** What should be explicitly excluded from this migration? For example, should Home Assistant stay on docker-compose, or should all services eventually move to K8s?

**Answer:**
- Exclude: Home Assistant (explicitly out of scope)
- Exclude: Applications already in K8s (Prometheus/Grafana, Ollama, Text Generation WebUI - though these may need revision since they're not running yet)
- Focus: Media stack (Plex, Radarr, Sonarr, qBittorrent, Jackett), Pi-hole, and other `docker/` applications

### Existing Code to Reference

**Similar Features Identified:**
- Feature: Existing ArgoCD Applications - Paths:
  - `k8s/llm-app.yaml` - Ollama LLM server deployment pattern
  - `k8s/prometheus-stack-app.yaml` - Monitoring stack deployment pattern
  - `k8s/elasticsearch-app.yaml` - ELK stack deployment pattern
- Pattern to reuse: Multi-source ArgoCD Application manifests (remote Helm chart + local values repository)
- Note: These applications aren't running yet, so they might need revision during migration work

**Additional Context:**
- Democratic CSI already configured with iSCSI and NFS storage classes (`freenas-iscsi-csi`, `freenas-nfs-csi`)
- NodePort is the preferred service type per project guidelines
- Synology Diskstation NFS share already mounted and visible in docker-compose files

### Follow-up Questions

None - all requirements clarified in first round.

## Visual Assets

### Files Provided:
No visual assets provided.

### Visual Insights:
N/A - No visual assets to analyze.

## Requirements Summary

### Functional Requirements

**Application Migration:**
- Scan and inventory all applications in `docker/` directory
- Convert docker-compose configurations to Kubernetes manifests or Helm charts
- Create ArgoCD Application resources for each service
- Configure services as NodePort type for external routing

**Storage Strategy:**
- Use iSCSI storage class (`freenas-iscsi-csi`, RWO) for:
  - Application databases
  - Application configuration files
  - Single-writer persistent data
- Use NFS storage class (`freenas-nfs-csi`, RWX) for:
  - Shared media libraries accessed by multiple services
- Mount existing Synology Diskstation NFS share for media files

**Namespace Organization:**
- Group related services into logical namespaces:
  - `media`: Plex, Radarr, Sonarr, qBittorrent, Jackett
  - `infrastructure`: Pi-hole and similar infrastructure services
  - Additional namespaces as appropriate for service groupings

**Migration Procedures:**
- Document manual data migration procedures (not automated via Ansible)
- User will handle moving configs & metadata themselves
- Provide step-by-step procedures for each application

**Rollback Strategy:**
- Keep docker-compose files in place during migration
- Document cutover procedure with rollback steps for each service
- Mark `docker/` directory as "legacy" only after K8s deployments are validated

### Reusability Opportunities

**ArgoCD Application Pattern:**
- Reference existing ArgoCD manifests as templates:
  - `k8s/llm-app.yaml` - Multi-source pattern with Helm chart
  - `k8s/prometheus-stack-app.yaml` - Monitoring stack pattern
  - `k8s/elasticsearch-app.yaml` - Complex multi-component pattern
- Note: These may need revision as they're not yet operational

**Storage Configuration:**
- Leverage existing Democratic CSI storage classes:
  - `freenas-iscsi-csi` for RWO volumes
  - `freenas-nfs-csi` for RWX volumes
- Reference existing CSI configurations and values

**Service Exposure Pattern:**
- Follow project standard: NodePort services
- Reference existing NodePort service configurations

### Scope Boundaries

**In Scope:**
- Inventory all docker-compose applications in `docker/` directory
- Create Kubernetes manifests or Helm charts for identified applications
- Configure ArgoCD Application resources using multi-source pattern
- Create PersistentVolumeClaim configurations (iSCSI for app data, NFS for shared media)
- Configure NodePort services for all migrated applications
- Document manual data migration procedures for each application
- Document rollback procedures for each service
- Organize applications into logical namespaces
- Migration sequence planning:
  1. Non-critical services first (test the pattern)
  2. Infrastructure services (Pi-hole)
  3. Media stack last (most complex with most data)

**Out of Scope:**
- Home Assistant migration (remains on docker-compose)
- NGINX Proxy Manager routing configuration (external to K8s)
- Automated Ansible playbooks for data migration
- Applications already deployed in K8s:
  - Prometheus/Grafana (though may need revision)
  - Ollama (though may need revision)
  - Text Generation WebUI (though may need revision)
- LoadBalancer or Ingress service types (NodePort only)
- Automated migration scripts (manual procedures preferred)

### Technical Considerations

**Kubernetes Cluster:**
- 3 control plane nodes + 3 worker nodes deployed via Kubespray
- ArgoCD operational and ready for application management
- MetalLB available but not used (NodePort preferred)
- Traefik available but not used for these applications (NodePort preferred)

**Storage Backend:**
- Democratic CSI with dual backends:
  - iSCSI (FreeNAS) for ReadWriteOnce volumes
  - NFS (FreeNAS) for ReadWriteMany volumes
- Existing Synology Diskstation NFS share for media files

**Service Exposure:**
- All services exposed as NodePort
- External routing handled by NGINX Proxy Manager + Unifi router (out of scope)
- No LoadBalancer or Ingress configuration needed

**ArgoCD Pattern:**
- Multi-source Application pattern:
  - Remote Helm chart repository as primary source
  - Local Git repository for values files
  - Automated sync with CreateNamespace policy
- Reference existing patterns in `k8s/*-app.yaml` files

**Migration Strategy:**
- Manual data migration procedures (user-driven)
- Phased rollout: non-critical → infrastructure → media stack
- Rollback capability maintained throughout migration
- Docker-compose files preserved until validation complete

**Application Priorities:**
- Focus applications from `docker/` directory:
  - Media stack: Plex, Radarr, Sonarr, qBittorrent, Jackett
  - Infrastructure: Pi-hole
  - Other applications as discovered in inventory
- Explicitly excluded:
  - Home Assistant (stays on docker-compose)
  - Applications already in K8s (may need separate revision work)
