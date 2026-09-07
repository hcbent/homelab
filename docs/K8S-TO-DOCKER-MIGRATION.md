# Migrating regularly-used apps from Kubernetes to the Docker Compose VM

Moves eight apps off the `homelab-kubespray` cluster onto a single Proxmox VM
(`docker`, vmid **113** on pve1) managed by Docker Compose, plus qBittorrent.

| App | Namespace (source) | Host port on VM |
|-----|--------------------|-----------------|
| jackett | media | 9117 |
| qbittorrent | media | 8080 (+6881) |
| sonarr | media | 8989 |
| radarr | media | 7878 |
| unpackerr | media | 5656 |
| tautulli | media | 8181 |
| maintainerr | media | 6246 |
| actualbudget | home-apps | 5006 |
| mealie (+ postgres) | home-apps | 9925 |

Two compose stacks run on the one VM:
- `/opt/docker/media` ← `docker/docker-compose.yml` (media-net)
- `/opt/docker/home-apps` ← `docker/home-apps/docker-compose.yml` (home-apps-net)

Storage: media library + downloads are Docker NFS volumes to the Synology
(`192.168.1.230:/volume1/video` and `.../downloads`); app config is local
bind mounts under `/opt/docker/media/<app>` migrated from the K8s iSCSI PVCs.

> **Ordering matters:** copy each app's config onto the VM and restore the
> Mealie Postgres dump *before* the first `docker compose up`, or the *arr apps
> initialize empty databases.

---

## 1. Provision the VM (Terraform)

`tf/home-apps/terraform.tfvars` is gitignored (it holds Proxmox + cloud-init
secrets). Add this VM block to the `home_app_vms` list (generate a skeleton with
`tf/add-vm.sh docker 113 4 8192 60G`):

```hcl
{
  name           = "docker"
  target_node    = "pve1.lab.thewortmans.org"
  vmid           = "113"
  clone          = "ubuntu-25.04"
  os_type        = "linux"
  cores          = "4"
  memory         = "8192"
  sockets        = "1"
  disk_size      = "60G"
  disk_storage   = "tank"
  network_model  = "virtio"
  network_bridge = "vmbr0"
  ipconfig0      = "ip=192.168.10.210/24,gw=192.168.10.1"
}
```

```bash
cd tf/home-apps
terraform plan  -var-file terraform.tfvars
terraform apply -var-file terraform.tfvars
```

## 2. Base host setup (Ansible)

`docker` is already in `[home_apps]` in `ansible/inventory/home`; its address is
set in `ansible/host_vars/docker/main.yml` (`ansible_host: 192.168.10.210` —
adjust if DHCP gives another IP).

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml   # community.docker, ansible.posix
ansible-playbook -i inventory/home playbooks/00_setup-host.yml --limit docker
```

## 3. Save the maintainerr image (do this FIRST — ttl.sh tags expire)

maintainerr runs a custom build `ttl.sh/maintainerr-viewcount-fix-v3:24h`.
On the cluster node running the pod, export it before it disappears:

```bash
# Find the node
kubectl get pod -n media -l app.kubernetes.io/name=maintainerr -o wide
# On that node (containerd/CRI):
sudo ctr -n k8s.io images export maintainerr.tar ttl.sh/maintainerr-viewcount-fix-v3:24h
#   (or: sudo nerdctl -n k8s.io save -o maintainerr.tar ttl.sh/maintainerr-viewcount-fix-v3:24h)

# Copy to the VM and load:
scp maintainerr.tar bret@192.168.10.210:/tmp/
ssh bret@192.168.10.210 'docker load -i /tmp/maintainerr.tar'
```

Then set the loaded tag in `ansible/host_vars/docker/main.yml`:
`docker_maintainerr_image: "ttl.sh/maintainerr-viewcount-fix-v3:24h"`.
If the tag has already expired and can't be recovered, fall back to
`ghcr.io/jorenn92/maintainerr:latest` (default) and re-add the config.

## 4. Migrate app config (with the K8s app scaled down for a clean copy)

For each config PVC, tar it out of the pod and extract into the VM bind mount.
Container config paths: `/config` for the *arr/jackett/qbittorrent/tautulli,
`/opt/data` for maintainerr, `/data` for actualbudget, `/app/data` for mealie.

```bash
# Example: sonarr (repeat for radarr, jackett, qbittorrent, unpackerr, tautulli)
kubectl scale -n media deploy/sonarr --replicas=0
kubectl run -n media tmp-copy --image=busybox --restart=Never --rm -i \
  --overrides='{"spec":{"volumes":[{"name":"c","persistentVolumeClaim":{"claimName":"sonarr-config"}}],"containers":[{"name":"c","image":"busybox","command":["tar","czf","-","-C","/config","."],"volumeMounts":[{"name":"c","mountPath":"/config"}]}]}}' \
  > sonarr-config.tgz
scp sonarr-config.tgz bret@192.168.10.210:/tmp/
ssh bret@192.168.10.210 'sudo mkdir -p /opt/docker/media/sonarr/config && \
  sudo tar xzf /tmp/sonarr-config.tgz -C /opt/docker/media/sonarr/config && \
  sudo chown -R 1000:1000 /opt/docker/media/sonarr/config'
```

> If an app is still running (not scaled down), `kubectl exec <pod> -- tar czf - -C /config .`
> works too, but stop the *arr apps first — their SQLite DBs must be copied at rest.

maintainerr → `/opt/docker/media/maintainerr/data`; actualbudget →
`/opt/docker/home-apps` uses the named volume `actualbudget_data`, so restore
into the volume mountpoint (`docker volume create home-apps_actualbudget_data`
then extract into `/var/lib/docker/volumes/home-apps_actualbudget_data/_data`),
or bind-mount actualbudget to a host dir if you prefer.

## 5. Migrate the Mealie Postgres database

```bash
kubectl exec -n home-apps deploy/mealie-postgres -- \
  pg_dump -U mealie -Fc mealie > mealie.dump
scp mealie.dump bret@192.168.10.210:/tmp/

# Match the mealie image tag to the cluster (schema is version-locked):
kubectl get deploy mealie -n home-apps -o jsonpath='{.spec.template.spec.containers[*].image}'
# → set docker_mealie_image in host_vars/docker/main.yml accordingly.
```

Bring up only Postgres first, restore, then start Mealie:

```bash
ssh bret@192.168.10.210
cd /opt/docker/home-apps
docker compose up -d mealie-postgres
docker compose cp /tmp/mealie.dump mealie-postgres:/tmp/mealie.dump   # or docker cp
docker exec -i mealie-postgres pg_restore -U mealie -d mealie --clean --if-exists /tmp/mealie.dump
docker compose up -d mealie
```

Also copy the Mealie `/app/data` (recipe images) into the `mealie_data` volume.

## 6. Fill secrets and deploy the stacks

Put real values in `ansible/host_vars/docker/vault.yml`, then encrypt it:

- `vault_unpackerr_sonarr_api_key` / `vault_unpackerr_radarr_api_key` — the
  Sonarr/Radarr **API keys from the migrated configs** (Settings → General →
  API Key). Unpackerr auths with these; they must match or you'll see 401s.
- `vault_mealie_postgres_password` — must match the password used in the restore.

```bash
cd ansible
ansible-vault encrypt host_vars/docker/vault.yml
ansible-playbook -i inventory/home playbooks/deploy_docker_apps.yml
```

This installs Docker CE + the Compose v2 plugin + `nfs-common`, lays down both
compose files and their `.env` secrets under `/opt/docker`, and brings the
stacks up.

## 7. Cut over ingress (NGINX Proxy Manager @ 192.168.10.250)

Repoint each proxy host's upstream from the cluster NodePort to the VM:

| Proxy host | New upstream |
|-----------|--------------|
| actualbudget | 192.168.10.210:5006 |
| mealie | 192.168.10.210:9925 |
| sonarr | 192.168.10.210:8989 |
| radarr | 192.168.10.210:7878 |
| jackett | 192.168.10.210:9117 |
| tautulli | 192.168.10.210:8181 |
| maintainerr | 192.168.10.210:6246 |
| qbittorrent | 192.168.10.210:8082 |

## 8. Decommission the K8s workloads (after sign-off)

Keep the manifests and PVCs as rollback; just stop the pods:

```bash
kubectl scale -n media     deploy/jackett deploy/qbittorrent deploy/sonarr \
  deploy/radarr deploy/unpackerr deploy/tautulli deploy/maintainerr --replicas=0
kubectl scale -n home-apps deploy/actualbudget deploy/mealie deploy/mealie-postgres --replicas=0
```

Rollback = point the NPM upstream back at the cluster NodePort and scale the
deployment back to 1.

## Verification

1. `docker compose ps` in `/opt/docker/media` and `/opt/docker/home-apps` — all healthy; `docker logs` clean.
2. Inside sonarr/radarr, `/data` (library) and `/downloads` are populated and group-writable (confirms NFS mounts + `UMASK=000`).
3. Sonarr/Radarr show existing series/movies, indexers, quality profiles; Download Client (qBittorrent `http://qbittorrent:8080`) and Jackett indexers test green.
4. Unpackerr logs show successful Sonarr/Radarr auth (no 401s) → API keys match.
5. Actualbudget opens the existing budget; Mealie lists existing recipes and `/api/app/about` reports the expected version; Tautulli connects to Plex with history; maintainerr rules/collections intact.
6. Each app loads externally through NPM from the VM.

## Notes / deviations

- **actualbudget**: `ACTUAL_ENCRYPTION_KEY` was not added to the compose env —
  migrating `/data` preserves all server state and the key is a client-side
  concern for end-to-end-encrypted files, not a required server variable.
- **paperless-ngx** already exists in `docker/home-apps/docker-compose.yml` but
  is out of scope for this migration; it is left untouched.
- qBittorrent gets both `/data` and `/downloads` mounts for path parity with the
  *arr apps; verify its saved download path after migrating its config.
