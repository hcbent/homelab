# Kibana: proposed design (Phase 6)

**Status: PROPOSED on 2026-11-09. Nothing here is built.** It is written for the operator to review first, because it adds machines and
credentials to a live cluster and settles how a person signs in to it. Items marked *to confirm* are from knowledge of Kibana and Elasticsearch
and have not been checked against this project's versions. The acceptance test in `IMPLEMENTATION_PLAN.md` is: the Kibana health check passes
on the disposable target, and a Caddy snippet is generated while the existing Caddyfile is untouched.

## What is known (read in the code on 2026-11-09)

- **Kibana is nowhere yet.** Only the plan, a "planned" `kibana_instances` table in ARCHITECTURE (which no later design used: desired state lives in
  the cluster's parameters, not in tables), and a note in `REPO_AUDIT.md` that the old `kibana` role should be rewritten clean-room.
- **A machine is one instance of the Terraform module**, `module.node["<name>"]`, fed by a map of `{node_name, vm_id, cores, memory_mb,
  os_disk_gb, data_disk_gb?, address, gateway}`. Ownership (`created_machines`), the plan rules (`node_of`), the teardown's allowed deletes and the
  VM-ID and address allocation all read that address and the `vm_ids` and `addresses` tables. A Kibana VM made as another entry of the same map
  would be checked, torn down and kept out of "foreign" machines by what exists, with no new rule.
- **Several places assume every address and every `module.node` is an Elasticsearch node:** the inventory refuses an address for a name that is
  not a node of the state ("addresses for unknown node(s)"), the restart, removal and recovery planners walk `state.nodes`, and the quorum and
  placement rules count master-eligible nodes. A Kibana machine must therefore live in its own list in the desired state, and only be *rendered*
  into the Terraform map.
- **Packages are installed by `es_package`**: the Elastic apt repository with a pinned signing-key fingerprint check, an exact version, a hold, and a
  refusal to change an installed version (an upgrade is a Phase 8 operation). The same pattern fits Kibana's package.
- **Certificates are issued by `es_tls`** with the cluster CA, which ECM stores encrypted and hands to Ansible as extra vars; only a host that lacks
  a certificate gets one. A Kibana host needs one too (its name, address and the public name).
- **ECM already holds an API key** for each cluster (made at bootstrap with the `elastic` user's full rights, stored encrypted) and the CA. The
  worker uses them for every Elasticsearch call it makes over HTTPS, and it can reach the VMs over SSH.
- **ECM does not keep the `elastic` password.** It is generated at create, used once to bootstrap, and deleted. So today **nobody has a login to the
  cluster except ECM's API key.** That is the question Kibana makes unavoidable (decision 2).
- **ECM never edits the Caddyfile** (`caddy/Caddyfile.example` says so). It can show a snippet.

## What Kibana needs (to confirm for the pinned version)

- **The same version as Elasticsearch** (Kibana must not be newer; ECM would install the cluster's exact version), from the same apt repository, held
  at that version. Port 5601. It is stateless: its saved objects are in Elasticsearch indices, so losing a Kibana machine loses no dashboards.
- **A service-account token for `elastic/kibana`**, not a username and password: `POST /_security/service/elastic/kibana/credential/token/<name>`,
  returned once. Made by the worker with ECM's API key (which has the rights), stored encrypted by ECM, and put in Kibana's keystore
  (`elasticsearch.serviceAccountToken`), never in `kibana.yml`.
- **Three encryption keys** (`xpack.security.encryptionKey`, `xpack.encryptedSavedObjects.encryptionKey`, `xpack.reporting.encryptionKey`), at least 32
  characters each, made once by ECM and stored encrypted. They protect saved objects that hold secrets (alerting connectors, API keys): **losing them
  loses those objects**, and a replacement Kibana must be given the same ones. They also go in the keystore.
- **TLS to Elasticsearch** with the cluster CA (`elasticsearch.ssl.certificateAuthorities`), and a list of Elasticsearch addresses to talk to (decision 6).
- **Its own TLS** for the browser side (`server.ssl.*`) and `server.publicBaseUrl`, which Kibana requires when a proxy sits in front.
- **Memory:** a Node.js process that wants at least about 1 GiB of its own; a small cluster's Kibana is comfortable at 2 cores, 4 GiB and a 32 GB disk, with no
  data disk.

## The sequence

Adding Kibana to a built cluster is a `tf.update` whose change is `add_kibana`, with add-node's phases (`render, init, plan, approval, apply,
configure`). A create with Kibana (decision 8) uses the same pieces.

1. **Plan (changes nothing).** The request names the host (optional), the size (defaults above) and the public name (optional). ECM places the machine on
   an online host with room (no quorum rule applies), allocates an address and a VM ID from the same pools as nodes, names it `<cluster>-kb-01`, and shows
   all of it. **Refused:** a cluster that is not built or has no record; no elected master or a red cluster (it cannot make the token); a cluster that
   already has Kibana (decision 1); a version ECM cannot install; no room on any host; a template that cannot be read from the host.
2. **Approve, then apply.** Terraform makes the one VM (the plan must create exactly that machine and nothing else, like a rebuild's plan).
3. **Configure** runs a new `add_kibana.yml`:
   1. the worker asks the cluster for a service token (with ECM's API key), unless ECM already holds one for this Kibana (a retry), and keeps it encrypted;
   2. wait for first boot, prepare the OS (`os_base`), install the Kibana package at the cluster's version (`kibana_package`, in the pattern of
      `es_package`);
   3. issue a certificate for the Kibana machine with the stored CA (`es_tls`, extended to a host group that is not an Elasticsearch node);
   4. write `kibana.yml`, put the token and the three keys in the keystore, start the service;
   5. **health check from the worker** with ECM's API key: `GET https://<kibana>:5601/api/status` until `overall.level` is `available` (Kibana accepts an
      API key for its own API; *to confirm*), and fail with the status if it does not.
4. **Record.** The cluster's desired state gains a `kibana` entry (name, VM ID, address, host, size, public name) as soon as Terraform has applied, as
   for every update.

A **failure** after the machine exists keeps it, and Retry runs the configure again (it asks for no second token). Removing a Kibana that will not come
up is the remove operation below, or a teardown.

**Removing Kibana** (`remove_kibana`, typed cluster name): no drain, since it holds no data. Terraform destroys the machine and the token is deleted from
Elasticsearch (`DELETE .../credential/token/<name>`). The encryption keys are kept by ECM, so a Kibana added later can read the old saved objects.
Dashboards and the rest stay in Elasticsearch.

**A teardown** of the cluster destroys the Kibana machine with the rest, with no change to the teardown's rules, since it is a resource of the same
module.

## What is shown to the operator

- A **Kibana panel** on the cluster page: its address and public name, whether the last health check passed, and **Add Kibana** (size, host, public name)
  or **Remove Kibana**. The panel also shows the **Caddy snippet** (below) and offers the **cluster CA** for download.
- The **Caddy snippet**, generated and shown, never applied:

  ```
  kibana.lab.example.org {
  	reverse_proxy https://192.168.10.116:5601 {
  		transport http { tls_trust_pool file /etc/caddy/ecm/<cluster>-ca.crt }
  	}
  }
  ```

  The proxy trusts Kibana through the cluster's CA, so TLS is verified end to end (`tls_insecure_skip_verify` is not used).
- **Sign-in details** (decision 2), shown once and then on request with an audit event.

## What has to be built

- **Desired state:** a `kibana` list (name, size, optional host and public name) and its validation; the VM, address and ID tables carry the Kibana name, but
  every ES-node walk keeps reading `state.nodes`. The inventory accepts addresses for Kibana names and has a `kibana` host group.
- **Terraform render:** Kibana machines merged into the module's map (a `tags` value of `kibana` rather than the ES one is *to decide* when the render is touched).
- **Credentials:** a service token and three encryption keys per cluster, stored with ECM's existing encrypted credential storage, redacted from every log.
- **Ansible:** `kibana_package` and `kibana` roles, `add_kibana.yml`, `remove_kibana` handled by Terraform plus one worker-side call; `es_tls` for a host that is not a node.
- **Rules** in `lifecycle.py` (`plan_add_kibana`, `plan_remove_kibana`), the plan rule (create exactly the Kibana machine; delete exactly it), ownership
  (nothing new), and the operation's configure step for the two kinds.
- **API and UI:** `POST /api/clusters/{id}/add-kibana` and `remove-kibana`, the panel, the plan tables, the sign-in reveal.
- **Tests:** the rules and refusals; the plan rules; the operation with fakes; the playbook against a fake Elasticsearch and Kibana (token requested once, a
  retry reusing it, the health check passing and failing); the keystore and key handling; and one live run on a disposable cluster, which also answers the *to confirm* items.

## Decisions for the operator

1. **How many Kibana instances.** *Proposed:* one per cluster in this phase, with the data model a list so more can come later. The alternative is several
   from the start (a list in the request, several machines, each its own token), which multiplies the plan page and the health checks.
2. **How a person signs in.** ECM does not keep the `elastic` password. *Proposed:* when Kibana is added, ECM **resets the `elastic` password** to a generated one
   (ECM's API key is unaffected, since it is an API key), stores it encrypted, shows it once, and shows it again on request with an audit event. The alternative is a
   separate superuser (for example `kibana-admin`) created the same way, which leaves `elastic` as it is but gives the operator a login that is not the one everyone
   knows. A third option is no login at all (Kibana runs, and the operator makes users another way), which is correct but leaves the page unusable.
3. **Kibana's own TLS.** *Proposed:* HTTPS with a certificate from the cluster CA, and Caddy trusting that CA (the snippet above). The alternative is plain HTTP on the private
   network behind Caddy, which is simpler and sends session cookies unencrypted across the lab network.
4. **Default size and host.** *Proposed:* 2 cores, 4 GiB, a 32 GB OS disk, no data disk, on the online host with the most room; the operator may choose the host and size.
5. **The public name.** *Proposed:* optional. It sets `server.publicBaseUrl`, the certificate's names and the Caddy snippet; left empty, Kibana is addressed by its IP and the
   snippet says to add a name.
6. **Which Elasticsearch nodes Kibana talks to.** *Proposed:* the nodes that are not master-only (up to three), as explicit HTTPS addresses, with no sniffing. When nodes are
   added or removed, the list is rewritten by the next converge and Kibana is **restarted by ECM** (a new "Restart Kibana" in the panel, since Kibana is stateless and the restart is
   brief). The alternative is to leave a stale list, which Kibana tolerates while any listed node is up.
7. **Order of building.** *Proposed:* 6a add Kibana to a built cluster (roles, playbook, health check, token and keys, panel, Caddy snippet); 6b remove Kibana, the sign-in reveal and
   Restart Kibana; 6c the option at create time.
8. **Create-time Kibana.** *Proposed:* the wizard gets an optional Kibana step, and the create plans the Kibana machine **in the same Terraform plan** (one approval) and runs the Kibana play
   after the cluster bootstraps. The alternative is simpler and slower for the operator: the create finishes, then the wizard starts an Add Kibana operation with its own approval.

## To confirm

- The exact service-token call and the right it needs (`manage_service_account`, which the `elastic` user's API key should carry), and that the token is shown once.
- `kibana-keystore add` for `elasticsearch.serviceAccountToken` and the three keys, and that the keystore is read at start.
- That Kibana's `/api/status` answers an `Authorization: ApiKey` request, and the field that says it is available.
- That the `elastic` password can be reset with an API key's rights (`POST /_security/user/elastic/_password`), and that nothing of ECM's depended on the old one (it does not: ECM uses the API key).
- Kibana's real memory use at 4 GiB on this cluster's data, and its start time (the health check's wait is a guess until measured).
- That Caddy's `tls_trust_pool file` is the right name in the Caddy version on infra.

## Risks

- **Losing the encryption keys** loses encrypted saved objects; ECM stores them encrypted and a backup of ECM's database is the backup of them.
- **The reset password is a superuser password** shown in a browser; it is shown only to a signed-in ECM admin, once by default, with an audit event on every reveal.
- **A Kibana newer than its Elasticsearch** will not start; the install pins the cluster's version. An upgrade (Phase 8) has to go in the other order from what a careless one would: Elasticsearch first, then Kibana, never Kibana ahead.
- **Kibana pointing at a node that is later removed** is harmless while another listed node is up, and is the reason for decision 6.
