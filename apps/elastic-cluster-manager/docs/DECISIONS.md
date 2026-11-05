# Decisions

## Made (ADR-style, revisable)
1. **Provider:** `bpg/proxmox`, exact-version pinned, subject to Milestone 0.
2. **Queue:** Procrastinate on Postgres, no Redis.
3. **TF state:** `pg` backend, one schema per cluster, plus encrypted snapshots.
4. **Clean-room** Terraform module and Ansible roles. The legacy `tf/modules/proxmox_vm` and `ansible/roles/elasticsearch` are not reused.
5. **Ansible** via `ansible-runner`, with a generated ephemeral inventory.
6. **ES versions** come from `artifacts-api.elastic.co/v1/versions` with a cache. Nothing hardcoded.
7. **Cluster identity** is `cluster_uuid`. VM correlation needs verified evidence.

## Answered by the user (2026-10-30)
1. **Terraform** (not OpenTofu), behind a runner interface.
2. **Proxmox:** a dedicated token is approved. Disposable VMs use **VMID 5xx**. Host is any pve node. The token itself is still to be provided (not by committing it).
3. **SSH to Proxmox nodes:** approved, with a dedicated key.
4. **Template:** selected by **VMID, default 8000**, as a setting (`ECM_DEFAULT_TEMPLATE_VMID`). `ECM_DEFAULT_TEMPLATE_NAME=ubuntu-25.04` is the fallback. Open question for the spike: confirm 8000 is a template on which node.
5. **Network:** VLAN 10, `192.168.10.0/24`. A DHCP-excluded static range is still to be chosen by the user. UniFi version is still unknown.
6. **Hosting:** Caddy on `infra.lab.thewortmans.org`. The app is `ecm.lab.thewortmans.org`.
7. **The existing cluster (es01–es06) is live.** Read-only discovery and adoption target only.
8. **Admin credential:** an Argon2id hash in the `ECM_ADMIN_PASSWORD_HASH` environment variable. This is more secure than a plaintext password variable, and a first-run page would be an open window before setup.
9. **Secrets policy (hard rule):** secrets are never committed. Real env files are gitignored. Only `*.example` or `*.template` copies with placeholders are committed.

## Phase 3 implementation notes
- **Deviation from ARCHITECTURE.md §10:** the VM link lives directly on `es_nodes` (`vm_id`, `link_confidence`, `link_evidence`) instead of a separate `vm_links` table. Simpler, and a node has at most one VM.
- **Proxmox connection:** one row per API endpoint. If pve1–3 form one PVE cluster, a single connection lists all three nodes. If they are standalone, add three connections. To be confirmed on the live system.
- **Correlation** uses the node's published IP against guest-agent IPs and static cloud-init IPs. Guest-agent evidence outranks configuration. MAC addresses are stored but ES does not report them, so they are not used.
- **Stale rows:** VMs, nodes and storage that disappear from a source are deleted from the observed-state tables on the next successful sync.
- **TLS:** verification is on by default. A pasted CA certificate or an explicit "skip verification" opt-in is available, and the opt-in is audited.
- **Fixtures are synthetic** (RFC 5737 addresses, invented names). They follow the real API response shapes but have not been checked against a live Proxmox or Elasticsearch yet.

## Adopted: Elastic UI (EUI) for the web app
- Requested 2026-10-30, implemented 2026-11-04 before Phase 4. Supersedes the shadcn/ui choice in ARCHITECTURE.md §1 (shadcn was never installed) and removes the hand-written Tailwind markup. `tailwindcss` and `@tailwindcss/vite` are uninstalled.
- **Stack:** `@elastic/eui` 123.3.0 with the Borealis theme, `@emotion/react`, `@emotion/css`, `@elastic/datemath`, `moment`. Light and dark follow the system preference, with a persisted override (`ecm.theme`). Colours come from the installed EUI theme; `theme.tsx` copies the tokens into CSS variables for the plain stylesheet.
- **License (checked against `node_modules/@elastic/eui/LICENSE.txt`):** the default is a dual license under the Server Side Public License v1 and the Elastic License 2.0. Use inside this self-hosted, single-tenant app, which is not offered to third parties as a hosted or managed service, is the ordinary case both licenses allow. Re-check if ECM is ever offered as a service. This is a reading of the license text, not legal advice.
- **Bundle size (measured, `npm run build`):** the main chunk is 2,366 KB (653 KB gzip) against about 164 KB before. EUI also emits about 530 lazy icon and logo chunks, 4.4 MB in `dist/assets`, which the browser only fetches when an icon is used. Accepted for a self-hosted tool. Code splitting by route is the first lever if it ever matters.
- **Fonts:** Inter and Roboto Mono are self-hosted variable files in `frontend/public/fonts/` with their OFL notices. `ensureFonts()` waits for `document.fonts.ready` and sets `data-fonts="loaded"` on `<html>` only when `document.fonts.check` passes for every used weight.
- **Screens:** sign-in (health key beside the form), clusters (summary tiles plus table), cluster detail (four cards plus tabs), infrastructure (Proxmox and Elasticsearch panels, add-connection form, inventory), operations, help. Routes and API calls are unchanged.
- **Phase 4 foundations:** `CreateClusterSteps` (wizard strip) and `ConfirmAction` (names the resource, requires the typed name for destructive actions) are built and tested but are not linked from navigation and never call the API.
- **Deviations from the page blueprint, with reasons:**
  - The cluster table has Name, Health, Version, Nodes, Infrastructure, Ownership and Last sync. Storage and JVM heap moved off the table (too many columns for two thirds of the width); storage is a card on cluster detail and JVM heap is on the Nodes card.
  - Connection rows show name, API URL, last sync and any sync error. TLS state is not shown because the API does not return it, and the API contract is unchanged.
  - The operation card shows the state, phase, duration and ID the API reports as log lines. The API has no log lines, started time or target, so none are invented and the copy says "state and phase".
  - Elasticsearch connection rows list registered clusters (from `/api/clusters`), since an Elasticsearch connection is a registered cluster.
  - Add-connection errors show the server message in one callout, not per field, because the API does not say which field failed. The Name field only applies to Proxmox.
  - Row changes on refresh tint the row for 260 ms; the health dot does not crossfade.
  - The wizard step strip is `EuiStepsHorizontal`, not a custom 3x2 grid.
  - The sign-in headline wraps to three lines below about 1100px, because the required copy is longer than the reference headline.
- **Browser evidence (Chromium via Playwright against the production build, mocked API, 1440, 820 and 390 px wide):** fonts loaded and `document.fonts.check` true for Inter 400 to 700 and Roboto Mono 400 and 500; no horizontal overflow on any screen; every interactive target at least 44 by 44; the sign-in entrance and dashboard tile stagger run once and do not replay on refresh; below-the-fold reveals stay hidden until reached, then play once; rapid scroll down and up twice, reload at a scrolled position, resize and a reduced-motion toggle during playback all leave every reachable section visible; reduced motion runs no entrance animations.
