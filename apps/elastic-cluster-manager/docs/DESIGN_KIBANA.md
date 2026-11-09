# Kibana: proposed design (Phase 6)

**Status: APPROVED on 2026-11-09 with all eight proposals accepted as written. Slice 6a is built, tested offline and run live once (2026-11-09, `test-5a`, per the operator's log). Slice 6b (the sign-in, Restart Kibana, Remove Kibana) is built, tested offline and run live (per the operator, 2026-11-09: everything worked as expected). Slice 6c (Kibana at create time) is built and tested offline and has not run on any real machine (see "Slice 6a as built", "Slice 6b as built" and "Slice 6c as built").** It was written for the operator to review first, because it adds machines and
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

**The operator's answers (2026-11-09): all eight as proposed.**

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

## Slice 6a as built (2026-11-09)

What exists, and the choices made while building it that the design left open:

- **Where Kibana is recorded.** `params["kibana"]`, a list beside `state` (`app/desired/kibana.py`: `KibanaSpec`), not inside `DesiredState`, and not in the
  node-keyed `placement`, `addresses` and `vm_ids`. Every walk of the Elasticsearch nodes is unchanged. The places that must know about the machine
  say so explicitly: the Terraform render (`RenderInput.kibana`, merged into the module's one map, no data disk), ownership (`machine_vm_ids`, so the
  machine is ECM's once its apply is recorded and the foreign-machine check covers it), address and VMID reservations while the operation is in flight,
  teardown (the credentials and the inventory row go with the cluster), and the plan rule (`check_add_kibana_plan`: create exactly that machine, delete
  and replace nothing).
- **The operation.** `tf.update` with `change.kind = "add_kibana"`, phases `render, init, plan, approval, apply, configure`. `POST /api/clusters/{id}/add-kibana`
  (also refuses a version the apt repository cannot supply) and `GET /api/clusters/{id}/ca.crt`.
- **Planning** (`plan_add_kibana`): a live read of the cluster (an elected master, not red; yellow is accepted because only the token needs the cluster),
  `<cluster>-kb-01`, the online host with the most room by the same fit rules and score as the nodes (`recommend_host`) or the host asked for, the template
  readable from it, an address and VMID from the same pools. No new quorum rule applies.
- **Credentials.** Two encrypted `Credential` rows per cluster: the service token (`es-kibana-token-<id>`, stored even when the run then fails, since the cluster
  never shows it again) and the three encryption keys as JSON (`es-kibana-keys-<id>`, made once, reused by every later run). Both are registered for log redaction.
- **Name of the token role.** `kibana_credential`, not `kibana_token`: the parent `.gitignore` hides `*token*`, and the first draft's files were silently
  untracked. A test already forbids such names in the Ansible tree.
- **The panel** shows the machine, how the last Add Kibana ended (read from that operation, which includes the health check; there is no separate periodic check),
  the Caddy snippet when there is a public name, and the CA download. **No sign-in exists yet**, and the panel, the plan and the finished operation all say so.
- **Verified offline:** 59 backend tests of the rules, the render, the plan rule, ownership, the operation with fake Terraform and Ansible (including a failed
  configure whose retry reuses the same token and keys, and a teardown), the panel data and the endpoints; 31 of the inventory and the runner; 15 that run
  `kibana_credential.yml` and `kibana_health.yml` with real `ansible-playbook` against a local HTTPS server (they found and fixed a bug where the new token was not
  handed back, because a block's `when` was re-evaluated after the block set the variable it tested); 12 frontend tests; a syntax check of `add_kibana.yml`.
- **Run live on 2026-11-09** on the test cluster `test-5a` (Kibana 9.4.9; from the operator's log of the operation, which succeeded: 1 machine added, `ok=48 failed=0` on the
  Kibana machine). The log shows the service token was made with ECM's API key, the machine was installed (package, `es_tls` signing with the CA host's `certutil`, keystore, service),
  and `/api/status` answered an `ApiKey` request with Kibana available on the third look (two retries, about 20 seconds after it listened). The operator then reached Kibana in a
  browser and, as expected, could not sign in. See "To confirm" for which items that settles.
- **Not verified:** the items marked open in "To confirm" below; a retry after a failed configure on a real machine (only tested against fakes); and the Caddy snippet. `ansible-lint --profile production` reports `var-naming` findings on the new
  roles as it does on the existing ones (this machine's lint is stricter than the notes say it was, and lacks the collections); the two long lines the new code
  introduced were fixed.
- **Left for later slices:** a public name added after the fact, and a VM `tags` value for
  Kibana (the machine carries the cluster's tags for now).

## Slice 6b as built (2026-11-09)

Built after the first live run of 6a, at the operator's request ("do all of that before we test"). **Tested offline only; none of it has run on a real machine.**

- **The sign-in (decision 2).** `POST /api/clusters/{id}/kibana-login` plans, and after approval a worker-run operation (`es.kibana`, no Terraform, phases `plan, approval, kibana`) sets a
  new generated password for the `elastic` user through `playbooks/kibana_login.yml` with ECM's API key, then signs in with it to prove it works. ECM keeps
  `{username, current, pending, reset_at}` encrypted. **The order is what keeps it from being lost:** the new password is stored as *pending* before the cluster is asked, only a
  proved password becomes *current*, and a reset that fails anywhere leaves the old one current; a retry sets the same pending password again. Only *current* is ever shown.
  `POST /api/clusters/{id}/kibana-login/reveal` returns it, records `kibana.login.reveal` in the audit log on every call (who, when, never the password) and sends `Cache-Control: no-store`.
  **How "shown once and again on request" was built:** the password is hidden by default and shown only on an explicit request, and every request is audited; ECM does not limit how
  many times. A successful reset is audited as `kibana.login.set`. The panel and the lifecycle payload carry only whether a sign-in is set and when, never the password.
- **The operation runs only what was approved.** Its digest is recomputed from the parameters about to run, not just compared with the stored one (a test found the stored comparison would
  not notice a plan changed after approval; `es.restart` has the same gap, which is not changed here).
- **Restart Kibana (decision 6).** `POST /api/clusters/{id}/restart-kibana`; `playbooks/restart_kibana.yml` rewrites `kibana.yml` from the cluster's current nodes (`kibana` role's
  `config.yml`), restarts the service once (the role's handler stands down so it does not restart it a second time), waits for it and runs the health check. Each Kibana records the
  Elasticsearch addresses it was last given (`es_hosts`), and the panel says when they differ from the cluster's current ones. A Kibana recorded before this was kept has none and is
  never reported out of date.
- **Remove Kibana.** `POST /api/clusters/{id}/remove-kibana` with the cluster name typed. A `tf.update` whose plan must destroy exactly the Kibana machine (`check_removal_plan`),
  then `playbooks/remove_kibana.yml` deletes the service token (a token already gone is fine, so a retry passes). The token is forgotten by ECM; **the encryption keys and the sign-in
  are kept**, so a Kibana added later reads the old saved objects and the password still works. The machine stops being ECM's, its inventory row goes at once, and its address is free again.
- **Run live on 2026-11-09, per the operator:** the sign-in, Restart Kibana and Remove Kibana "worked as expected" on `test-5a`. The operator's logs of these were not seen, so
  this records the report and no detail. The one defect found was in the UI: the copy button of the sign-in details copied the labels and both values; the username and password are now
  separate blocks and each copy button copies exactly its own value (`3de4a84`). This settles that Elasticsearch accepts ECM's API key for the change-password call.

## Slice 6c as built (2026-11-09)

Kibana at create time, per decision 8 ("planned in the same Terraform plan as the cluster, with one approval"). **Tested offline only; none of it has run on a real machine.**

- **The request.** `POST /api/clusters` takes an optional `kibana` (`public_name`, `cores`, `ram_mb`, `os_disk_gb`, `pve_node`; all optional; the same model as Add Kibana). The wizard has a
  **Kibana step** after Sizing (a switch, off by default, with the same fields); the review shows where Kibana would run and the final step says whether it is part of the build.
- **One plan, one approval.** The Kibana machine is placed after the nodes, by the same code Add Kibana uses (`plan_kibana_machine`), **with the nodes' planned capacity already counted against each host**
  (so a host with room for a node or for Kibana but not both is not promised twice), an address and a VMID from the same pools, and recorded in `params["kibana"]` beside the state. The Terraform
  render already merges that list, so the create's plan is simply one machine longer and the plan rule for a create (create only) needs no change. What will be configured is part of the approved
  digest, and now ends "then install Kibana … on `<cluster>-kb-01` … and check it reports itself available", so a create with Kibana cannot be approved as one without.
- **The order.** The create's configure step builds the cluster exactly as before; once it has bootstrapped, the same operation runs the Add Kibana play on the machine the same plan made
  (token with ECM's API key, package, certificate, keystore, service, health check). The cluster is recorded as built *before* Kibana is attempted.
- **If Kibana fails.** The cluster, its credentials and the Kibana machine are kept and on record, the token is stored even though the run failed, and the operation fails at its last step.
  **Retry skips the cluster build** (it is already bootstrapped), plans nothing new, needs no second approval, and runs the Kibana step again with the same token and keys. A retry after Kibana
  succeeded does nothing. (`kibana_added` in the operation's result records that it ran.)
- **Everything else follows from the machine being in `params["kibana"]`:** it is ECM's once the apply is recorded, its address and VMID are reserved while the create is in flight, a teardown
  destroys it with the cluster and names it in the panel, and the panel's "last added" points at the create when that is how Kibana was added.
- **No sign-in is made at create time.** The create knows the `elastic` password it generated, but it is still deleted after bootstrap, as before; use Create sign-in afterwards (the plan, the
  create's result and the panel all say so). Keeping the bootstrap password as the sign-in would avoid a second change of the superuser's password; it was not done because decision 2 says to reset.

## To confirm

Settled by the live run of 2026-11-09 (the operator's log; the log does not show the HTTP bodies, so only what it implies is claimed):

- **Service-token call and rights:** settled. ECM's API key could make the `elastic/kibana` token (no refusal), and it was handed back and stored.
- **`kibana-keystore add` with `--stdin --force`:** settled. All four secrets were added, and Kibana started and reached Elasticsearch with them, since it reported available.
- **`/api/status` with `Authorization: ApiKey`:** settled. It answered and `overall.level` reached `available`; the check verified Kibana's certificate against the cluster CA by IP.
- **Start time:** about 20 seconds from listening to available on this cluster (the wait allows 600).

Still open:

- **Settled by the operator's report on 2026-11-09 ("everything worked as expected"):** that the `elastic` password can be reset with ECM's API key and then signed in with, that `restart_kibana.yml` works, and that Remove Kibana works. Their logs were not seen.
- **Kibana at create time (6c) on a real cluster:** the first run is what shows whether the one plan places the Kibana machine sensibly on a real Proxmox, and whether the Kibana step after bootstrap works on a just-built cluster.
- Kibana's real memory use at 4 GiB on this cluster's data, and its start time (the health check's wait is a guess until measured).
- That Caddy's `tls_trust_pool file` is the right name in the Caddy version on infra.

## Risks

- **Losing the encryption keys** loses encrypted saved objects; ECM stores them encrypted and a backup of ECM's database is the backup of them.
- **The reset password is a superuser password** shown in a browser; it is shown only to a signed-in ECM admin, once by default, with an audit event on every reveal.
- **A Kibana newer than its Elasticsearch** will not start; the install pins the cluster's version. An upgrade (Phase 8) has to go in the other order from what a careless one would: Elasticsearch first, then Kibana, never Kibana ahead.
- **Kibana pointing at a node that is later removed** is harmless while another listed node is up, and is the reason for decision 6.
