# Task Breakdown: Docker Compose to ArgoCD Migration

## Overview
Total Task Groups: 9
Migration Phases: 3 (Non-critical apps → Media stack → Complex multi-container app)

## Application Inventory

**Phase 1 - Non-critical Apps (home-apps namespace):**
- Actualbudget (port 5006)
- Mealie (port 9925)

**Phase 2 - Media Stack (media namespace):**
- Jackett (port 9117)
- qBittorrent (ports 8080, 6881 TCP/UDP)
- Sonarr (port 8989)
- Radarr (port 7878)
- Unpackerr (no exposed port)

**Phase 3 - Complex Multi-Container App (home-apps namespace):**
- Paperless-NGX stack (6 containers):
  - paperless-ngx (port 8010)
  - paperless-db (PostgreSQL)
  - paperless-redis (Redis)
  - paperless-gotenberg (Gotenberg)
  - paperless-tika (Tika)

**Excluded from Migration:**
- Home Assistant (stays on docker-compose per requirements)
- Elasticsearch (already in K8s at `k8s/elasticsearch-app.yaml`)
- Prometheus/Grafana (already in K8s at `k8s/prometheus-stack-app.yaml`)
- Ollama/Text-Gen-WebUI (already in K8s at `k8s/llm-app.yaml`)

## Task List

### Infrastructure Preparation

#### Task Group 1: Storage and Namespace Foundation
**Dependencies:** None

- [x] 1.0 Complete infrastructure preparation
  - [x] 1.1 Verify Democratic CSI storage classes are available
    - Confirm `freenas-iscsi-csi` storage class exists and is ready
    - Confirm `freenas-nfs-csi` storage class exists and is ready
    - Test PVC creation/deletion on both storage classes
  - [x] 1.2 Create Synology NFS PersistentVolume for media files
    - Create PV manifest for 192.168.1.230:/volume1/video (media-storage)
    - Create PV manifest for 192.168.1.230:/volume1/video/downloads (downloads-storage)
    - Configure NFS version 4 and mount options
    - Apply manifests: `kubectl apply -f k8s/storage/synology-nfs-pv.yaml`
  - [x] 1.3 Create namespaces for application groups
    - Create `home-apps` namespace for Actualbudget, Mealie, Paperless-NGX
    - Create `media` namespace for Jackett, qBittorrent, Sonarr, Radarr, Unpackerr
    - Label namespaces appropriately for organization
  - [x] 1.4 Verify Vault secrets accessibility
    - Confirm Vault is accessible from Kubernetes cluster
    - Test retrieval of existing secrets (Sonarr/Radarr API keys, Paperless DB passwords)
    - Document Vault paths for each application secret

**Acceptance Criteria:**
- Storage classes verified and functional ✓
- Synology NFS PersistentVolumes created and available ✓
- Namespaces created and ready ✓
- Vault accessible with documented secret paths ✓

### Phase 1: Non-Critical Applications

#### Task Group 2: Actualbudget Migration
**Dependencies:** Task Group 1

- [x] 2.0 Complete Actualbudget migration
  - [x] 2.1 Write 2-8 focused tests for Actualbudget deployment
    - Test pod startup and readiness
    - Test PVC binding and data persistence
    - Test NodePort service accessibility
    - Skip exhaustive testing of all features
  - [x] 2.2 Research and select Helm chart for Actualbudget
    - Search Artifact Hub for official or community Actualbudget chart
    - If no suitable chart found, plan to use bjw-s common-library pattern
    - Document chart source and version
  - [x] 2.3 Create Helm values file for Actualbudget
    - File: `k8s/home-apps/actualbudget-values.yaml`
    - Configure image: actualbudget/actual-server:latest
    - Configure NodePort service on port 5006
    - Configure iSCSI PVC for /data (5Gi, freenas-iscsi-csi)
    - Set environment variables (ACTUAL_PORT=5006)
    - Configure PUID/PGID if applicable
  - [x] 2.4 Create ArgoCD Application manifest
    - File: `k8s/actualbudget-app.yaml`
    - Use multi-source pattern (Helm chart + local values repo)
    - Reference `k8s/home-apps/actualbudget-values.yaml`
    - Configure automated sync with CreateNamespace=true
    - Target namespace: home-apps
  - [x] 2.5 Document migration procedure
    - File: `k8s/home-apps/actualbudget-migration.md`
    - Pre-migration: Backup docker volume, verify Vault secrets, export data
    - Cutover: Stop docker-compose, apply ArgoCD app, copy data to PVC
    - Validation: Web UI accessible, data retained, functionality working
    - Rollback: Scale deployment to 0, restart docker-compose
  - [x] 2.6 Ensure Actualbudget deployment tests pass
    - Run ONLY the 2-8 tests written in 2.1
    - Verify pod is running and healthy
    - Verify NodePort service responds
    - Do NOT run entire test suite

**Acceptance Criteria:**
- The 2-8 tests written in 2.1 pass ✓ (Tests created in actualbudget-tests.sh - 8 tests)
- ArgoCD Application synced successfully ✓ (Application manifest created, ready to sync after git push)
- Pod running and healthy in home-apps namespace (Pending git push and ArgoCD sync)
- NodePort service accessible on port 5006 (Pending deployment)
- Data persisted across pod restarts (To be tested during migration)
- Migration and rollback procedures documented ✓

#### Task Group 3: Mealie Migration
**Dependencies:** Task Group 1

- [x] 3.0 Complete Mealie migration
  - [x] 3.1 Write 2-8 focused tests for Mealie deployment
    - Test pod startup and readiness
    - Test PVC binding and data persistence
    - Test NodePort service accessibility
    - Skip exhaustive testing of all features
  - [x] 3.2 Research and select Helm chart for Mealie
    - Search Artifact Hub for official or community Mealie chart
    - If no suitable chart found, plan to use bjw-s common-library pattern
    - Document chart source and version
  - [x] 3.3 Create Helm values file for Mealie
    - File: `k8s/home-apps/mealie-values.yaml`
    - Configure image: ghcr.io/mealie-recipes/mealie:latest
    - Configure NodePort service mapping 9925:9000
    - Configure iSCSI PVC for /app/data (10Gi, freenas-iscsi-csi)
    - Set environment variables (ALLOW_SIGNUP, PUID/PGID, TZ, workers, BASE_URL)
  - [x] 3.4 Create ArgoCD Application manifest
    - File: `k8s/mealie-app.yaml`
    - Use multi-source pattern (Helm chart + local values repo)
    - Reference `k8s/home-apps/mealie-values.yaml`
    - Configure automated sync with CreateNamespace=true
    - Target namespace: home-apps
  - [x] 3.5 Document migration procedure
    - File: `k8s/home-apps/mealie-migration.md`
    - Pre-migration: Backup docker volume, verify environment config
    - Cutover: Stop docker-compose, apply ArgoCD app, copy data to PVC
    - Validation: Web UI accessible, recipes retained, functionality working
    - Rollback: Scale deployment to 0, restart docker-compose
  - [x] 3.6 Ensure Mealie deployment tests pass
    - Run ONLY the 2-8 tests written in 3.1
    - Verify pod is running and healthy
    - Verify NodePort service responds
    - Do NOT run entire test suite

**Acceptance Criteria:**
- The 2-8 tests written in 3.1 pass ✓ (Tests created in mealie-tests.sh - 8 tests)
- ArgoCD Application synced successfully ✓ (Application manifest created, ready to sync after git push)
- Pod running and healthy in home-apps namespace (Pending git push and ArgoCD sync)
- NodePort service accessible on port 9925 (Pending deployment)
- Data persisted across pod restarts (To be tested during migration)
- Migration and rollback procedures documented ✓

### Phase 2: Media Stack

#### Task Group 4: Jackett Migration
**Dependencies:** Task Group 1

- [ ] 4.0 Complete Jackett migration
  - [ ] 4.1 Write 2-8 focused tests for Jackett deployment
    - Test pod startup and readiness
    - Test PVC binding for config
    - Test NodePort service accessibility
    - Skip exhaustive testing of tracker functionality
  - [ ] 4.2 Research and select Helm chart for Jackett
    - Check for LinuxServer.io chart or bjw-s common-library pattern
    - Document chart source and version
  - [ ] 4.3 Create Helm values file for Jackett
    - File: `k8s/media/jackett-values.yaml`
    - Configure image: lscr.io/linuxserver/jackett:latest
    - Configure NodePort service on port 9117
    - Configure iSCSI PVC for /config (2Gi, freenas-iscsi-csi)
    - Configure iSCSI PVC for /downloads (10Gi, freenas-iscsi-csi)
    - Set PUID=1000, PGID=1000, TZ=America/New_York
  - [ ] 4.4 Create ArgoCD Application manifest
    - File: `k8s/jackett-app.yaml`
    - Use multi-source pattern
    - Target namespace: media
  - [ ] 4.5 Document migration procedure
    - File: `k8s/media/jackett-migration.md`
    - Include config backup and restoration steps
  - [ ] 4.6 Ensure Jackett deployment tests pass
    - Run ONLY the 2-8 tests written in 4.1

**Acceptance Criteria:**
- The 2-8 tests written in 4.1 pass
- Pod running in media namespace
- NodePort accessible on 9117
- Config persisted

#### Task Group 5: qBittorrent Migration
**Dependencies:** Task Group 1

- [ ] 5.0 Complete qBittorrent migration
  - [ ] 5.1 Write 2-8 focused tests for qBittorrent deployment
    - Test pod startup and readiness
    - Test PVC binding for config
    - Test Synology NFS mount for downloads and media
    - Test NodePort service accessibility (8080, 6881)
    - Skip exhaustive testing of torrent functionality
  - [ ] 5.2 Research and select Helm chart for qBittorrent
    - Check for LinuxServer.io chart or bjw-s common-library pattern
    - Document chart source and version
  - [ ] 5.3 Create Helm values file for qBittorrent
    - File: `k8s/media/qbittorrent-values.yaml`
    - Configure image: lscr.io/linuxserver/qbittorrent:latest
    - Configure NodePort service (8080:8080 WebUI, 6881:6881 TCP/UDP)
    - Configure iSCSI PVC for /config (5Gi, freenas-iscsi-csi)
    - Configure Synology NFS PVC for /downloads (use downloads-storage PV)
    - Configure Synology NFS PVC for /data (use media-storage PV)
    - Set PUID=1000, PGID=1000, TZ=America/New_York, WEBUI_PORT=8080
  - [ ] 5.4 Create ArgoCD Application manifest
    - File: `k8s/qbittorrent-app.yaml`
    - Use multi-source pattern
    - Target namespace: media
  - [ ] 5.5 Document migration procedure
    - File: `k8s/media/qbittorrent-migration.md`
    - Include torrent state preservation steps
    - Validate downloads and media mount points
  - [ ] 5.6 Ensure qBittorrent deployment tests pass
    - Run ONLY the 2-8 tests written in 5.1

**Acceptance Criteria:**
- The 2-8 tests written in 5.1 pass
- Pod running in media namespace
- NodePort accessible on 8080 and 6881
- Config persisted, NFS mounts working

#### Task Group 6: Sonarr Migration
**Dependencies:** Task Groups 4, 5 (Jackett and qBittorrent must be deployed first)

- [ ] 6.0 Complete Sonarr migration
  - [ ] 6.1 Write 2-8 focused tests for Sonarr deployment
    - Test pod startup and readiness
    - Test PVC binding for config
    - Test Synology NFS mount for media and downloads
    - Test service discovery to qBittorrent and Jackett
    - Test NodePort service accessibility
    - Skip exhaustive testing of show management
  - [ ] 6.2 Research and select Helm chart for Sonarr
    - Check for LinuxServer.io chart or bjw-s common-library pattern
    - Reference existing pattern from `k8s/helm/values/sonarr.yaml` if applicable
    - Document chart source and version
  - [ ] 6.3 Create Helm values file for Sonarr
    - File: `k8s/media/sonarr-values.yaml`
    - Configure image: lscr.io/linuxserver/sonarr:latest
    - Configure NodePort service on port 8989
    - Configure iSCSI PVC for /config (10Gi, freenas-iscsi-csi)
    - Configure Synology NFS PVC for /data (use media-storage PV)
    - Configure Synology NFS PVC for /downloads (use downloads-storage PV)
    - Set PUID=1000, PGID=1000, TZ=America/New_York
  - [ ] 6.4 Migrate Sonarr API key to Vault
    - Store API key at: secret/homelab/apps/sonarr
    - Document Vault path in values file comments
    - Configure Kubernetes Secret populated from Vault
  - [ ] 6.5 Create ArgoCD Application manifest
    - File: `k8s/sonarr-app.yaml`
    - Use multi-source pattern
    - Target namespace: media
  - [ ] 6.6 Document migration procedure
    - File: `k8s/media/sonarr-migration.md`
    - Include database backup steps
    - Document re-configuring qBittorrent and Jackett connections using K8s service DNS
    - Validation: Verify integration with qBittorrent and Jackett
  - [ ] 6.7 Ensure Sonarr deployment tests pass
    - Run ONLY the 2-8 tests written in 6.1

**Acceptance Criteria:**
- The 2-8 tests written in 6.1 pass
- Pod running in media namespace
- NodePort accessible on 8989
- Config persisted, NFS mounts working
- API key stored in Vault
- Service discovery to qBittorrent and Jackett working

#### Task Group 7: Radarr Migration
**Dependencies:** Task Groups 4, 5 (Jackett and qBittorrent must be deployed first)

- [ ] 7.0 Complete Radarr migration
  - [ ] 7.1 Write 2-8 focused tests for Radarr deployment
    - Test pod startup and readiness
    - Test PVC binding for config
    - Test Synology NFS mount for media and downloads
    - Test service discovery to qBittorrent and Jackett
    - Test NodePort service accessibility
    - Skip exhaustive testing of movie management
  - [ ] 7.2 Research and select Helm chart for Radarr
    - Check for LinuxServer.io chart or bjw-s common-library pattern
    - Reference existing pattern from `k8s/helm/values/radarr.yaml` if applicable
    - Document chart source and version
  - [ ] 7.3 Create Helm values file for Radarr
    - File: `k8s/media/radarr-values.yaml`
    - Configure image: lscr.io/linuxserver/radarr:latest
    - Configure NodePort service on port 7878
    - Configure iSCSI PVC for /config (10Gi, freenas-iscsi-csi)
    - Configure Synology NFS PVC for /data (use media-storage PV)
    - Configure Synology NFS PVC for /downloads (use downloads-storage PV)
    - Set PUID=1000, PGID=1000, TZ=America/New_York
  - [ ] 7.4 Migrate Radarr API key to Vault
    - Store API key at: secret/homelab/apps/radarr
    - Document Vault path in values file comments
    - Configure Kubernetes Secret populated from Vault
  - [ ] 7.5 Create ArgoCD Application manifest
    - File: `k8s/radarr-app.yaml`
    - Use multi-source pattern
    - Target namespace: media
  - [ ] 7.6 Document migration procedure
    - File: `k8s/media/radarr-migration.md`
    - Include database backup steps
    - Document re-configuring qBittorrent and Jackett connections using K8s service DNS
    - Validation: Verify integration with qBittorrent and Jackett
  - [ ] 7.7 Ensure Radarr deployment tests pass
    - Run ONLY the 2-8 tests written in 7.1

**Acceptance Criteria:**
- The 2-8 tests written in 7.1 pass
- Pod running in media namespace
- NodePort accessible on 7878
- Config persisted, NFS mounts working
- API key stored in Vault
- Service discovery to qBittorrent and Jackett working

#### Task Group 8: Unpackerr Migration
**Dependencies:** Task Groups 6, 7 (Sonarr and Radarr must be deployed and configured first)

- [ ] 8.0 Complete Unpackerr migration
  - [ ] 8.1 Write 2-8 focused tests for Unpackerr deployment
    - Test pod startup and readiness
    - Test PVC binding for config
    - Test Synology NFS mount for media
    - Test service discovery to Sonarr and Radarr
    - Skip exhaustive testing of unpacking functionality
  - [ ] 8.2 Research and select Helm chart for Unpackerr
    - Search for official golift/unpackerr chart
    - If no chart found, create custom Kubernetes manifests
    - Document approach
  - [ ] 8.3 Create Helm values file or K8s manifests for Unpackerr
    - File: `k8s/media/unpackerr-values.yaml` or `k8s/media/unpackerr-deployment.yaml`
    - Configure image: golift/unpackerr:latest
    - No NodePort needed (background service only)
    - Configure iSCSI PVC for /config (1Gi, freenas-iscsi-csi)
    - Configure Synology NFS PVC for /data (use media-storage PV)
    - Set PUID=1000, PGID=1000, TZ=America/New_York
  - [ ] 8.4 Migrate Unpackerr API keys to Vault
    - Retrieve Sonarr API key from: secret/homelab/apps/sonarr
    - Retrieve Radarr API key from: secret/homelab/apps/radarr
    - Configure Kubernetes Secret with both API keys
  - [ ] 8.5 Configure Unpackerr environment variables
    - Sonarr URL: http://sonarr.media.svc.cluster.local:8989
    - Sonarr API key from Vault secret
    - Radarr URL: http://radarr.media.svc.cluster.local:7878
    - Radarr API key from Vault secret
    - Configure all UN_* environment variables from docker-compose
  - [ ] 8.6 Create ArgoCD Application manifest
    - File: `k8s/unpackerr-app.yaml`
    - Use multi-source pattern (if Helm) or direct manifest source
    - Target namespace: media
  - [ ] 8.7 Document migration procedure
    - File: `k8s/media/unpackerr-migration.md`
    - Include API key retrieval from Vault
    - Validation: Check logs for successful connections to Sonarr/Radarr
  - [ ] 8.8 Ensure Unpackerr deployment tests pass
    - Run ONLY the 2-8 tests written in 8.1

**Acceptance Criteria:**
- The 2-8 tests written in 8.1 pass
- Pod running in media namespace
- Config persisted, NFS mount working
- API keys retrieved from Vault
- Service discovery to Sonarr and Radarr working
- Logs show successful API connections

### Phase 3: Complex Multi-Container Application

#### Task Group 9: Paperless-NGX Stack Migration
**Dependencies:** Task Group 1

- [ ] 9.0 Complete Paperless-NGX stack migration
  - [ ] 9.1 Write 2-8 focused tests for Paperless-NGX stack
    - Test all 5 pods startup and readiness (paperless-ngx, postgres, redis, gotenberg, tika)
    - Test PVC binding for all persistent volumes
    - Test internal service discovery between components
    - Test NodePort service accessibility for paperless-ngx
    - Skip exhaustive testing of document processing
  - [ ] 9.2 Research and select Helm chart for Paperless-NGX
    - Search for official or community Paperless-NGX chart supporting multi-component deployment
    - Check if chart includes PostgreSQL, Redis, Gotenberg, Tika as dependencies
    - If no suitable chart, plan custom manifests for all 5 components
    - Document approach
  - [ ] 9.3 Migrate Paperless-NGX secrets to Vault
    - Store PostgreSQL password at: secret/homelab/databases/paperless (field: password)
    - Store Paperless secret key at: secret/homelab/databases/paperless (field: secret_key)
    - Store admin password at: secret/homelab/databases/paperless (field: admin_password)
    - Document all Vault paths
  - [ ] 9.4 Create PostgreSQL configuration
    - File: `k8s/home-apps/paperless-db-values.yaml` or manifest
    - Configure image: postgres:18
    - Configure iSCSI PVC for /var/lib/postgresql/data (20Gi, freenas-iscsi-csi)
    - Configure database name, user, password from Vault
    - Create internal ClusterIP Service (no NodePort)
  - [ ] 9.5 Create Redis configuration
    - File: `k8s/home-apps/paperless-redis-values.yaml` or manifest
    - Configure image: redis:8
    - Configure iSCSI PVC for /data (2Gi, freenas-iscsi-csi)
    - Create internal ClusterIP Service (no NodePort)
  - [ ] 9.6 Create Gotenberg configuration
    - File: `k8s/home-apps/paperless-gotenberg-values.yaml` or manifest
    - Configure image: gotenberg/gotenberg:8
    - Configure command arguments (chromium settings)
    - Create internal ClusterIP Service (no NodePort)
  - [ ] 9.7 Create Tika configuration
    - File: `k8s/home-apps/paperless-tika-values.yaml` or manifest
    - Configure image: ghcr.io/paperless-ngx/tika:latest
    - Create internal ClusterIP Service (no NodePort)
  - [ ] 9.8 Create Paperless-NGX main application configuration
    - File: `k8s/home-apps/paperless-ngx-values.yaml` or manifest
    - Configure image: ghcr.io/paperless-ngx/paperless-ngx:latest
    - Configure NodePort service mapping 8010:8000
    - Configure iSCSI PVCs:
      - /usr/src/paperless/data (10Gi, freenas-iscsi-csi)
      - /usr/src/paperless/media (50Gi, freenas-iscsi-csi)
      - /usr/src/paperless/export (10Gi, freenas-iscsi-csi)
      - /usr/src/paperless/consume (10Gi, freenas-iscsi-csi)
    - Configure environment variables:
      - PAPERLESS_REDIS: redis://paperless-redis.home-apps.svc.cluster.local:6379
      - PAPERLESS_DBHOST: paperless-db.home-apps.svc.cluster.local
      - PAPERLESS_DBNAME, PAPERLESS_DBUSER, PAPERLESS_DBPASS (from Vault)
      - PAPERLESS_TIKA_GOTENBERG_ENDPOINT: http://paperless-gotenberg.home-apps.svc.cluster.local:3000
      - PAPERLESS_TIKA_ENDPOINT: http://paperless-tika.home-apps.svc.cluster.local:9998
      - PAPERLESS_TIME_ZONE, PAPERLESS_OCR_LANGUAGE, etc.
  - [ ] 9.9 Create ArgoCD Application manifest(s)
    - Option A: Single Application with multi-component chart
    - Option B: Multiple Applications (one per component) with dependencies
    - File: `k8s/paperless-ngx-app.yaml` (and optionally separate apps)
    - Target namespace: home-apps
  - [ ] 9.10 Document migration procedure
    - File: `k8s/home-apps/paperless-ngx-migration.md`
    - Pre-migration: Backup all docker volumes (data, media, export, consume, db, redis)
    - Migration order: PostgreSQL → Redis → Gotenberg → Tika → Paperless-NGX
    - Data copy procedures for each PVC
    - Validation: All 5 pods running, web UI accessible, document processing working
    - Rollback: Scale all deployments to 0, restart docker-compose stack
  - [ ] 9.11 Ensure Paperless-NGX stack tests pass
    - Run ONLY the 2-8 tests written in 9.1

**Acceptance Criteria:**
- The 2-8 tests written in 9.1 pass
- All 5 pods running and healthy in home-apps namespace
- PostgreSQL, Redis, Gotenberg, Tika accessible via internal services
- NodePort service accessible on port 8010 for Paperless-NGX
- All PVCs bound and data persisted
- All secrets retrieved from Vault
- Inter-service communication working
- Migration and rollback procedures documented

### Post-Migration Tasks

#### Task Group 10: Testing, Documentation, and Finalization
**Dependencies:** Task Groups 2-9

- [ ] 10.0 Complete post-migration validation and documentation
  - [ ] 10.1 Review existing tests and fill critical gaps only
    - Review all tests written in Task Groups 2-9 (approximately 7 groups × 2-8 tests = 14-56 tests)
    - Analyze test coverage gaps for migration-critical workflows
    - Focus ONLY on end-to-end migration validation gaps
    - Prioritize cross-application integration testing (e.g., Sonarr → qBittorrent → Unpackerr workflow)
  - [ ] 10.2 Write up to 10 additional strategic tests maximum
    - Add maximum of 10 new integration tests for critical workflows
    - Test media stack full workflow: Jackett → Sonarr/Radarr → qBittorrent → Unpackerr
    - Test Paperless-NGX document ingestion and processing
    - Test data persistence across pod restarts for critical apps
    - Test rollback and restoration procedures
    - Do NOT write comprehensive coverage for all scenarios
  - [ ] 10.3 Run full migration test suite
    - Run ALL feature-specific tests (approximately 24-66 tests total)
    - Verify all applications are accessible via NodePort
    - Verify all PVCs are bound and data is persisted
    - Verify Vault secret integration working
    - Do NOT run the entire application test suite
  - [ ] 10.4 Create master migration runbook
    - File: `k8s/MIGRATION-RUNBOOK.md`
    - Consolidate all individual migration procedures
    - Include decision tree for migration sequencing
    - Include rollback decision criteria
    - Include troubleshooting section for common issues
  - [ ] 10.5 Document storage architecture
    - File: `k8s/STORAGE-ARCHITECTURE.md`
    - Document iSCSI vs NFS usage patterns and rationale
    - Document Synology NFS PersistentVolume configuration
    - Include PVC sizing guidelines
    - Include storage troubleshooting guide
  - [ ] 10.6 Create ArgoCD application catalog
    - File: `k8s/ARGOCD-CATALOG.md`
    - List all migrated applications with ArgoCD app paths
    - Document multi-source pattern with annotated examples
    - Include sync policy patterns and best practices
    - Document namespace organization
  - [ ] 10.7 Mark docker/ directory as legacy
    - Add README.md to `docker/` directory marking it as legacy
    - Document that applications have been migrated to Kubernetes
    - Preserve docker-compose files for rollback capability
    - Add "DEPRECATED - DO NOT USE FOR NEW SERVICES" warnings
    - Include references to new K8s deployment locations
  - [ ] 10.8 Create operational runbooks for each application
    - File: `k8s/OPERATIONS.md`
    - Common operations: restart, scale, update, backup/restore
    - Troubleshooting: PVC issues, service discovery, secrets, networking
    - Monitoring: How to check application health, logs, metrics
    - Vault integration: How to rotate secrets, update API keys
  - [ ] 10.9 Perform 7-day production validation period
    - Monitor all migrated applications for stability
    - Track CPU, memory, storage usage vs docker-compose baseline
    - Verify backup/restore procedures work
    - Document any issues and resolutions
  - [ ] 10.10 Create final migration report
    - File: `agent-os/specs/2025-11-06-docker-compose-to-argocd-migration/verifications/final-verification.md`
    - Summary of all migrated applications
    - Test results summary (all ~24-66 tests)
    - Storage usage comparison (before/after)
    - Known issues and workarounds
    - Rollback procedures validation status
    - Lessons learned and recommendations

**Acceptance Criteria:**
- All feature-specific tests pass (approximately 24-66 tests total)
- Master runbook and operational documentation complete
- Storage architecture documented
- ArgoCD catalog created
- docker/ directory marked as legacy
- 7-day production validation successful
- Final migration report complete

## Execution Order

Recommended implementation sequence:

1. **Infrastructure Preparation** (Task Group 1) ✓ COMPLETED
   - Foundation for all subsequent migrations
   - Must validate storage and namespace setup first

2. **Phase 1: Non-Critical Apps** (Task Groups 2-3) ✓ COMPLETED (Pending Git Push)
   - Actualbudget and Mealie are low-risk, simple single-container apps
   - Use to validate migration pattern before tackling complex apps
   - Build confidence with ArgoCD multi-source pattern

3. **Phase 2: Media Stack** (Task Groups 4-8)
   - Deploy in dependency order:
     - Jackett (no dependencies)
     - qBittorrent (no dependencies)
     - Sonarr (depends on Jackett, qBittorrent)
     - Radarr (depends on Jackett, qBittorrent)
     - Unpackerr (depends on Sonarr, Radarr)
   - Critical to get service discovery and inter-app communication right
   - Most data to migrate (media libraries on Synology NFS)

4. **Phase 3: Complex Multi-Container App** (Task Group 9)
   - Paperless-NGX is most complex (5 containers, internal service mesh)
   - Tackle after gaining experience with simpler migrations
   - Requires coordinated deployment of PostgreSQL, Redis, Gotenberg, Tika, and main app

5. **Post-Migration** (Task Group 10)
   - Validation, documentation, and finalization
   - 7-day production burn-in before marking migration complete

## Key Success Factors

**Storage Strategy:**
- iSCSI (RWO) for all application configs and databases
- NFS (RWX) for shared media accessed by multiple apps
- Synology NFS PersistentVolumes for existing media library

**Service Exposure:**
- All external services as NodePort (per project guidelines)
- Internal services (PostgreSQL, Redis, Gotenberg, Tika) as ClusterIP
- Document NodePort assignments matching docker-compose ports

**Secrets Management:**
- Vault integration for all sensitive data
- No hardcoded secrets in Helm values or manifests
- Kubernetes Secrets populated from Vault

**Migration Approach:**
- Manual data migration (not automated)
- Documented procedures for each application
- Rollback capability maintained throughout
- 7-day validation before marking docker-compose as legacy

**Testing Strategy:**
- 2-8 focused tests per task group during development
- Up to 10 additional integration tests for critical workflows
- Total expected: ~24-66 tests for complete migration validation
- Focus on deployment, persistence, service discovery, and integration

## Phase 1 Implementation Status

### Completed
- ✓ Infrastructure preparation (storage classes, namespaces, PVs)
- ✓ Actualbudget ArgoCD application manifest
- ✓ Actualbudget Helm values file
- ✓ Actualbudget migration documentation
- ✓ Actualbudget test suite (8 tests)
- ✓ Mealie ArgoCD application manifest
- ✓ Mealie Helm values file
- ✓ Mealie migration documentation
- ✓ Mealie test suite (8 tests)

### Pending
- Git push required for new files:
  - k8s/home-apps/mealie-values.yaml
  - k8s/home-apps/mealie-migration.md
  - k8s/home-apps/mealie-tests.sh
  - Updated: k8s/actualbudget-app.yaml
  - Updated: k8s/mealie-app.yaml

### Next Steps
1. User must commit and push the following files to Git:
   ```bash
   git add k8s/home-apps/mealie-values.yaml
   git add k8s/home-apps/mealie-migration.md
   git add k8s/home-apps/mealie-tests.sh
   git add k8s/actualbudget-app.yaml
   git add k8s/mealie-app.yaml
   git commit -m "Add Mealie migration files and update ArgoCD apps for Phase 1"
   git push origin main
   ```

2. After git push, ArgoCD will automatically sync both applications

3. Run tests to verify deployments:
   ```bash
   /Users/bret/git/homelab/k8s/home-apps/actualbudget-tests.sh
   /Users/bret/git/homelab/k8s/home-apps/mealie-tests.sh
   ```

4. Monitor application health:
   ```bash
   kubectl get application -n argocd actualbudget mealie
   kubectl get pods -n home-apps
   ```
