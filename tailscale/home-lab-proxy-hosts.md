# NGINX Proxy Manager - home.lab Proxy Hosts

Add these 17 proxy hosts to NGINX Proxy Manager for Tailscale access.

**Access NGINX Proxy Manager:** http://truenas.shire-pangolin.ts.net:30020

## Configuration Settings (same for all)

- **Scheme:** http
- **SSL:** None (Tailscale handles encryption)
- **Websockets Support:** ON
- **Block Common Exploits:** ON

## Proxy Hosts to Create

| Domain Name | Forward Hostname/IP | Forward Port |
|-------------|---------------------|--------------|
| actual.home.lab | 192.168.10.250 | 5007 |
| argocd.home.lab | kube.lab.thewortmans.org | 8443 |
| cerebro.home.lab | bdwlb.myddns.me | 7008 |
| cchstest.home.lab | bdwlb.myddns.me | 7098 |
| df.home.lab | bdwlb.myddns.me | 7042 |
| dfk.home.lab | bdwlb.myddns.me | 7043 |
| elasticsearch.home.lab | bdwlb.myddns.me | 7005 |
| kibana.home.lab | bdwlb.myddns.me | 7004 |
| makerspace.home.lab | bdwlb.myddns.me | 7099 |
| mealie.home.lab | 192.168.10.250 | 9925 |
| monitoring.home.lab | bdwlb.myddns.me | 7009 |
| paperless.home.lab | bdwlb.myddns.me | 7007 |
| pihole.home.lab | bdwlb.myddns.me | 7012 |
| plex.home.lab | bdwlb.myddns.me | 7100 |
| qbittorrent.home.lab | kube.lab.thewortmans.org | 8090 |
| radarr.home.lab | 192.168.10.250 | 7878 |
| sonarr.home.lab | 192.168.10.250 | 8989 |

## Steps to Add Each Host

1. Click **Add Proxy Host**
2. **Details tab:**
   - Domain Names: `<service>.home.lab`
   - Scheme: `http`
   - Forward Hostname/IP: (from table above)
   - Forward Port: (from table above)
   - Enable: Websockets Support, Block Common Exploits
3. **SSL tab:** Leave disabled (no certificate needed)
4. Click **Save**

## After Adding All Hosts

Configure Tailscale split DNS to resolve `*.home.lab` to TrueNAS:
- TrueNAS Tailscale IP: 100.106.169.106

See Tailscale admin console: https://login.tailscale.com/admin/dns
