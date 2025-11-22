# Deferred Issues - Tailscale Migration

This document tracks issues discovered during the Tailscale migration that require future investigation.

## Task Group 4: NGINX Proxy Manager Deployment

### Services with 502 Bad Gateway (Backend Connectivity Issues)

The following two services are configured in NGINX Proxy Manager but return 502 Bad Gateway errors. These services route to backends on `bdwlab.myddns.me` (174.179.132.241) which may be down or have port forwarding issues.

**Status**: 86% success rate (12/14 services working)
**Note**: plex.home.lab was removed from NPM as it will not be accessed this way.

#### Non-Working Services

1. **paperless.home.lab**
   - Backend: bdwlab.myddns.me:7007
   - Error: 502 Bad Gateway
   - Likely cause: Backend service down or port 7007 not accessible

2. **pihole.home.lab**
   - Backend: bdwlab.myddns.me:7012
   - Error: 502 Bad Gateway
   - Likely cause: Backend service down or port 7012 not accessible

#### Investigation Steps (TODO)

- [ ] Verify bdwlab.myddns.me resolves correctly from NPM pod
- [ ] Check if ports 7007, 7012, 7100 are accessible from Kubernetes cluster
- [ ] Verify backend services are running on the target host
- [ ] Check port forwarding rules on router for these ports
- [ ] Test direct connectivity: `curl -I http://bdwlab.myddns.me:7007` etc.

#### Working Services (12/15)

These services are confirmed working through NPM:
- actual.home.lab (HTTPS backend with self-signed cert)
- argocd.home.lab
- cerebro.home.lab
- df.home.lab
- dfk.home.lab
- elasticsearch.home.lab
- kibana.home.lab
- mealie.home.lab
- monitoring.home.lab
- qbt.home.lab (qbittorrent)
- radarr.home.lab
- sonarr.home.lab

---

**Date identified**: 2025-11-20
**Task Group**: 4 - NGINX Proxy Manager Deployment
**Priority**: Medium (non-critical services, can be addressed in later task groups)
