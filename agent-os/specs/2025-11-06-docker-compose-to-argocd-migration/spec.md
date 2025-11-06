# Specification: Docker Compose to ArgoCD Migration

## Goal
Migrate existing docker-compose applications to Kubernetes manifests managed by ArgoCD, leveraging the newly deployed Kubespray cluster with Democratic CSI storage backend, while maintaining rollback capability throughout the migration process.

## User Stories
- As a homelab operator, I want my media stack applications managed declaratively in Kubernetes so that they benefit from K8s orchestration and self-healing
- As a system administrator, I want to migrate applications with documented rollback procedures so that I can revert to docker-compose if issues arise

## Specific Requirements

**Application Inventory and Prioritization**
- Identify all applications in the `docker/` directory requiring migration (media stack: Jackett, qBittorrent, Sonarr, Radarr, Unpackerr; home apps: Actualbudget, Mealie, Paperless-NGX stack)
- Exclude Home Assistant from migration (remains on docker-compose)
- Exclude applications already in Kubernetes (Prometheus/Grafana, Ollama, Text Generation WebUI)
- Organize applications into logical namespaces: `media` for media stack, `home-apps` for productivity applications
- Use phased migration sequence: non-critical services first (Actualbudget, Mealie), then infrastructure, then media stack (most complex with most data)

**Storage Strategy Implementation**
- Use Democratic CSI iSCSI storage class (`freenas-iscsi-csi`, RWO) for application configuration directories and databases (single-writer persistent data)
- Use Democratic CSI NFS storage class (`freenas-nfs-csi`, RWX) for shared media libraries accessed by multiple services
- Configure Synology Diskstation NFS share (192.168.1.230:/volume1/video) as PersistentVolume for media files already stored on Synology
- Create PersistentVolumeClaim configurations for each application's config storage and shared media access
- Maintain data persistence across pod restarts and rescheduling

**ArgoCD Application Pattern**
- Follow multi-source Application pattern: remote Helm chart as primary source + local Git repository for values files
- Reference existing pattern from `k8s/llm-app.yaml`, `k8s/prometheus-stack-app.yaml`, `k8s/elasticsearch-app.yaml`
- Configure automated sync with `CreateNamespace=true` policy for new namespaces
- Store Helm values files in structured directories under `k8s/[namespace]/[app-name].yaml`
- Use official Helm charts where available from trusted repositories (LinuxServer.io charts, bjw-s common chart)

**Service Exposure Configuration**
- Configure all services as NodePort type (not LoadBalancer or Ingress)
- Document NodePort assignments for each service to match existing docker-compose port mappings
- External routing via NGINX Proxy Manager is out of scope
- Map docker-compose port mappings (e.g., Jackett:9117, qBittorrent:8080, Sonarr:8989, Radarr:7878) to NodePort services

**Secrets Management**
- Integrate with HashiCorp Vault for secret retrieval (Sonarr/Radarr API keys, database passwords)
- Reference Vault paths documented in docker-compose files (e.g., `vault kv get -field=sonarr_api_key secret/homelab/apps/unpackerr`)
- Avoid hardcoded secrets in Helm values files
- Use Kubernetes Secret resources populated from Vault for sensitive environment variables

**Migration Procedures**
- Document manual data migration procedures for each application (not automated via Ansible)
- Include step-by-step cutover procedures: stop docker-compose service, copy config data to PVC, deploy ArgoCD application, validate functionality
- Create pre-migration checklist: backup docker-compose configs, verify Vault secrets, ensure storage classes available, confirm namespace exists
- Define validation criteria for each application: web UI accessible, API responding, database connectivity, file access working

**Rollback Strategy**
- Keep docker-compose files in place during migration (do not delete)
- Document rollback steps for each service: scale K8s deployment to 0, copy config back to docker host if needed, restart docker-compose service
- Mark `docker/` directory as "legacy" only after full validation period (minimum 7 days production operation)
- Create rollback decision criteria: persistent application failures, data corruption, performance degradation, critical feature unavailability

**Application-Specific Configuration**
- Paperless-NGX: Multi-component deployment (Paperless-NGX, PostgreSQL, Redis, Gotenberg, Tika) requiring internal service discovery
- Media stack: Configure inter-service dependencies (Sonarr/Radarr depend on qBittorrent and Jackett)
- Unpackerr: Configure API integration with Sonarr and Radarr using Kubernetes service DNS
- Configure PUID/PGID for LinuxServer.io containers (1000:1000) for file ownership consistency

**Monitoring and Validation**
- Define success criteria: application starts successfully, web UI accessible on NodePort, persistent data retained, inter-service communication working
- Document verification commands: `kubectl get pods -n [namespace]`, `kubectl logs -n [namespace] [pod-name]`, `kubectl exec` for connectivity tests
- Create post-deployment validation checklist per application
- Monitor resource usage (CPU, memory, storage) compared to docker-compose baseline

**Documentation Requirements**
- Create migration runbook for each application with prerequisites, steps, validation, and rollback procedures
- Document storage architecture decisions (why iSCSI vs NFS for each use case)
- Include ArgoCD Application manifest examples with annotations explaining multi-source pattern
- Provide troubleshooting guide for common issues (PVC binding failures, service discovery problems, permission issues)

## Existing Code to Leverage

**ArgoCD Multi-Source Application Pattern (`k8s/llm-app.yaml`, `k8s/prometheus-stack-app.yaml`)**
- Multi-source configuration with remote Helm chart repository as primary source
- Local Git repository reference for values files using `$values/` syntax
- Automated sync policy with namespace creation enabled
- Demonstrates destination configuration targeting local cluster
- Shows proper version pinning with `targetRevision` for Helm charts

**Democratic CSI Storage Configuration (`k8s/democratic-csi/values-iscsi.yaml`, `k8s/democratic-csi/values-nfs.yaml`)**
- Pre-configured storage classes `freenas-iscsi-csi` (RWO) and `freenas-nfs-csi` (RWX)
- ZFS dataset configuration for Kubernetes volumes on FreeNAS backend
- Storage class parameters including reclaim policy, volume binding mode, volume expansion support
- Shows proper credentials injection pattern using Vault

**Helm Values File Structure (`k8s/llm/ollama.yaml`)**
- Service type configuration (NodePort pattern with explicit nodePort assignments)
- PersistentVolume configuration using `storageClass: "freenas-iscsi-csi"`
- Environment variable configuration patterns
- Security context configuration (runAsUser, fsGroup, capabilities)
- Probe configuration for liveness and readiness checks

**Existing Media Stack Helm Values (`k8s/helm/values/radarr.yaml`, `k8s/helm/values/sonarr.yaml`)**
- Based on bjw-s common library chart pattern
- Persistence configuration for config and media volumes
- Custom liveness probes using API health checks
- Service port configuration matching application defaults
- Shows integration pattern for Prometheus metrics exporters

**Docker Compose Configuration Reference (`docker/docker-compose.yml`, `docker/home-apps/docker-compose.yml`)**
- Existing port mappings to replicate as NodePort services
- Volume mount patterns to translate to PVCs and PVs
- Environment variable patterns including Vault secret references
- Inter-service dependency chains to preserve in Kubernetes
- Synology NFS mount configuration (192.168.1.230:/volume1/video) to replicate as PersistentVolume

## Out of Scope
- Home Assistant migration (explicitly excluded, remains on docker-compose)
- NGINX Proxy Manager routing configuration (external routing handled outside Kubernetes)
- Automated Ansible playbooks for data migration (manual procedures preferred)
- LoadBalancer or Ingress service types (NodePort only per project guidelines)
- Migration of applications already deployed in Kubernetes (Prometheus/Grafana, Ollama, Text Generation WebUI may need separate revision work)
- Automated rollback scripts (manual rollback procedures documented instead)
- Performance optimization or scaling strategies beyond single-replica deployments
- Backup and disaster recovery automation (separate concern)
- Certificate management beyond existing step-certificates integration
- Monitoring and alerting configuration (leverage existing Prometheus/Grafana stack)
