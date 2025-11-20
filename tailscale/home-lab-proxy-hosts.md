# NGINX Proxy Manager - home.lab Proxy Hosts

Add these 17 proxy hosts to NGINX Proxy Manager for Tailscale access.

**Access NGINX Proxy Manager:** http://npm.shire-pangolin.ts.net:81

## Configuration Settings (default for most)

- **Scheme:** http (see exceptions below)
- **SSL:** None (Tailscale handles encryption)
- **Websockets Support:** ON
- **Block Common Exploits:** ON

## Proxy Hosts to Create

| Domain Name | Forward Hostname/IP | Forward Port | Scheme | Notes |
|-------------|---------------------|--------------|--------|-------|
| actual.home.lab | 192.168.10.250 | 5007 | **https** | Backend uses HTTPS |
| argocd.home.lab | kube.lab.thewortmans.org | 8443 | http | |
| cerebro.home.lab | bdwlb.myddns.me | 7008 | http | |
| cchstest.home.lab | bdwlb.myddns.me | 7098 | http | |
| df.home.lab | bdwlb.myddns.me | 7042 | http | |
| dfk.home.lab | bdwlb.myddns.me | 7043 | http | |
| elasticsearch.home.lab | bdwlb.myddns.me | 7005 | http | |
| kibana.home.lab | bdwlb.myddns.me | 7004 | http | |
| makerspace.home.lab | bdwlb.myddns.me | 7099 | http | |
| mealie.home.lab | 192.168.10.250 | 9925 | http | |
| monitoring.home.lab | bdwlb.myddns.me | 7009 | http | |
| paperless.home.lab | bdwlb.myddns.me | 7007 | http | |
| pihole.home.lab | bdwlb.myddns.me | 7012 | http | |
| plex.home.lab | bdwlb.myddns.me | 7100 | http | |
| qbittorrent.home.lab | kube.lab.thewortmans.org | 8090 | http | |
| radarr.home.lab | 192.168.10.250 | 7878 | http | |
| sonarr.home.lab | 192.168.10.250 | 8989 | http | |

## Steps to Add Each Host

1. Click **Add Proxy Host**
2. **Details tab:**
   - Domain Names: `<service>.home.lab`
   - Scheme: Use value from "Scheme" column in table above
   - Forward Hostname/IP: (from table above)
   - Forward Port: (from table above)
   - Enable: Websockets Support, Block Common Exploits
3. **SSL tab:** Leave disabled (no certificate needed - Tailscale handles encryption)
4. **Advanced tab (for HTTPS backends only):**
   - For services using HTTPS scheme (like actual.home.lab), add custom config:
     ```
     proxy_ssl_verify off;
     ```
5. Click **Save**

## Special Configuration Notes

### actual.home.lab (HTTPS Backend)
Since the backend uses HTTPS with a self-signed certificate:
- Set Scheme to `https`
- In Advanced tab, add: `proxy_ssl_verify off;`
- This disables SSL certificate verification for the backend connection

## DNS Configuration

Pi-hole DNS has been configured to resolve `*.home.lab` to NPM:
- NPM Tailscale IP: 100.123.46.74
- Configuration: `address=/home.lab/100.123.46.74` in Pi-hole dnsmasq_lines
