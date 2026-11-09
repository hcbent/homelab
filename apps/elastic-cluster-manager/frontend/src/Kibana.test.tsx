import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const SNIPPET = "kibana.lab.example.org {\n\treverse_proxy https://192.168.10.116:5601 {\n"
  + "\t\ttransport http { tls_trust_pool file /etc/caddy/ecm/lab-d-ca.crt }\n\t}\n}\n";
const MACHINE = { name: "lab-d-kb-01", vm_id: 520, address: "192.168.10.116", host: "pve2", cores: 2, ram_mb: 4096, os_disk_gb: 32,
  public_name: "kibana.lab.example.org", url: "https://192.168.10.116:5601", public_url: "https://kibana.lab.example.org",
  caddy_snippet: SNIPPET, hosts_out_of_date: false };
const NO_LOGIN = { set: false, reset_at: null, last: null };
const HAS_LOGIN = { set: true, reset_at: "2026-11-09T18:00:00Z", last: { operation_id: "lg1", state: "succeeded", finished_at: null } };
const NONE = { machines: [], can_add: true, can_change: false, ca_available: true, last_add: null, login: NO_LOGIN, last_restart: null };
/** A cluster that has Kibana, with what the panel is told about it. */
const WITH = (over: Record<string, unknown> = {}, machine: Record<string, unknown> = {}) => ({
  ...LIFE, kibana: { machines: [{ ...MACHINE, ...machine }], can_add: false, can_change: true, ca_available: true, last_add: null,
    login: NO_LOGIN, last_restart: null, ...over } });
const LIFE = { managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: true, can_remove: false,
  data_disks: {}, can_change: true, sizes: { "lab-d-01": { cores: 2, ram_mb: 4096 } }, kibana: NONE };
const INFRA = { connections: [], nodes: [{ name: "pve1", status: "online", usage: {} }, { name: "pve2", status: "online", usage: {} }],
  storages: [], templates: [], vms: [] };
const detail = (lifecycle: unknown) => ({
  id: "c1", name: "lab-d", uuid: null, version: "9.5.6", health: "green", ownership: "managed", nodes: 0, data_nodes: 0,
  infrastructure: { proxmox_hosts: [], verified_links: 0, total_nodes: 0 },
  storage: { total_bytes: 0, used_bytes: 0, used_pct: null }, jvm_heap_used_pct: null, jvm_heap_max_pct: null,
  last_sync_at: null, last_sync_error: null,
  elasticsearch: { health: {}, shards: { by_state: {}, by_node: {}, unassigned: [] }, settings: { persistent: {}, transient: {} } },
  desired: { managed: true, note: null }, node_list: [], lifecycle,
});

function app(lifecycle: unknown, extra: Record<string, [number, unknown]> = {}) {
  const routes = table({ "GET /api/clusters/c1": [200, detail(lifecycle)], "GET /api/infrastructure": [200, INFRA], ...extra });
  const handler: Handler = (url, init) =>
    url.endsWith("/me") ? [200, { username: "admin", role: "admin" }] : routes(url, init);
  const fn = mockFetch(handler);
  render(<App />);
  return fn;
}
const panel = () => screen.findByRole("heading", { name: "Kibana" });
const plan = () => screen.getByRole("button", { name: "Plan adding Kibana" });
const confirm = async () => {
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan adding Kibana" }));
};

test("a cluster without Kibana offers to add one and explains what that does and does not touch", async () => {
  app(LIFE);
  await panel();
  expect(screen.getByText(/The Elasticsearch nodes are not touched or restarted/)).toBeInTheDocument();
  expect(plan()).toBeEnabled();
});

test("with nothing filled in, the request is empty so ECM's defaults apply", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/add-kibana": [202, { operation_id: "k1", change: {} }] });
  await panel();
  await confirm();
  await waitFor(() => expect(window.location.hash).toBe("#/operations/k1"));
  expect(posted(fn, "/api/clusters/c1/add-kibana")).toEqual([{}]);
});

test("a public name, a host and a size are sent as asked, with RAM converted from GiB", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/add-kibana": [202, { operation_id: "k2", change: {} }] });
  await panel();
  await userEvent.type(screen.getByLabelText(/Public name/), "kibana.lab.example.org");
  await userEvent.type(screen.getByLabelText(/Cores/), "4");
  await userEvent.type(screen.getByLabelText(/RAM, GiB/), "8");
  await userEvent.type(screen.getByLabelText(/Disk, GB/), "64");
  await userEvent.selectOptions(screen.getByLabelText("Proxmox host"), "pve2");
  await confirm();
  await waitFor(() => expect(window.location.hash).toBe("#/operations/k2"));
  expect(posted(fn, "/api/clusters/c1/add-kibana")).toEqual([
    { public_name: "kibana.lab.example.org", pve_node: "pve2", cores: 4, ram_mb: 8192, os_disk_gb: 64 }]);
});

test("a public name with a scheme or a port, or a size out of range, blocks the button and says why", async () => {
  app(LIFE);
  await panel();
  const name = screen.getByLabelText(/Public name/);
  await userEvent.type(name, "https://kibana.example.org");
  await userEvent.tab();
  expect(await screen.findByRole("alert")).toHaveTextContent(/DNS name such as kibana.example.org/);
  expect(plan()).toBeDisabled();
  await userEvent.clear(name);
  await userEvent.type(screen.getByLabelText(/Cores/), "0");
  await userEvent.tab();
  expect(await screen.findByRole("alert")).toHaveTextContent("Cores must be a whole number from 1 to 64.");
  expect(plan()).toBeDisabled();
});

test("a refusal from the server is shown and nothing navigates", async () => {
  app(LIFE, { "POST /api/clusters/c1/add-kibana": [409, { detail: "the cluster is red, so some data is already unavailable" }] });
  await panel();
  await confirm();
  expect(await screen.findByRole("alert")).toHaveTextContent("the cluster is red");
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("while an operation runs, adding is not offered and the operation is linked", async () => {
  app({ ...LIFE, busy_operation_id: "op9", kibana: { ...NONE, can_add: false } });
  await panel();
  expect(screen.queryByRole("button", { name: "Plan adding Kibana" })).not.toBeInTheDocument();
  const kibana = within((await panel()).closest(".ecm-lifecycle") as HTMLElement);    // every panel shows its own link
  expect(kibana.getByRole("link", { name: "Open it" })).toHaveAttribute("href", "#/operations/op9");
});

test("a cluster that has Kibana shows it, its last check, the Caddy snippet that is never applied, and the CA download", async () => {
  app(WITH({ last_add: { operation_id: "k1", state: "succeeded", finished_at: "2026-11-09T18:00:00Z" } }));
  await panel();
  expect(screen.getByText("https://192.168.10.116:5601")).toBeInTheDocument();
  expect(screen.getByText("https://kibana.lab.example.org")).toBeInTheDocument();
  expect(screen.getByText("2 cores, 4 GiB, 32 GB disk")).toBeInTheDocument();
  expect(screen.getByText(/Reported itself available when it was added/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the operation" })).toHaveAttribute("href", "#/operations/k1");
  expect(screen.getByText(/ECM shows it and never edits the Caddyfile/)).toBeInTheDocument();
  expect(document.querySelector("pre, code")?.textContent).toContain("tls_trust_pool file /etc/caddy/ecm/lab-d-ca.crt");
  expect(document.body.textContent).not.toContain("tls_insecure_skip_verify");
  expect(screen.getByRole("link", { name: "Download the cluster CA certificate" })).toHaveAttribute("href", "/api/clusters/c1/ca.crt");
  expect(screen.queryByRole("button", { name: "Plan adding Kibana" })).not.toBeInTheDocument();   // one per cluster
});

test("a Kibana with no sign-in says nobody can sign in and offers to create one, and never shows a password", async () => {
  app(WITH());
  await panel();
  expect(screen.getByText("Nobody can sign in to this Kibana yet")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create sign-in" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show sign-in details" })).not.toBeInTheDocument();
  expect(screen.queryByText("Password")).not.toBeInTheDocument();
});

test("a Kibana added without a name has no snippet, and a failed add points at Retry", async () => {
  app(WITH({ ca_available: false, last_add: { operation_id: "k3", state: "failed", finished_at: null } },
    { public_name: null, public_url: null, caddy_snippet: null }));
  await panel();
  expect(screen.getByText(/added without a public name, so there is no snippet/)).toBeInTheDocument();
  expect(screen.getByText("Kibana did not finish being added")).toBeInTheDocument();
  expect(screen.getByText(/press Retry/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download the cluster CA certificate" })).not.toBeInTheDocument();
});

test("a cluster that is not built, or not managed by ECM, has no Kibana panel", async () => {
  app({ ...LIFE, bootstrapped: false });
  await screen.findByRole("heading", { name: "Add nodes" }).catch(() => null);
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Kibana" })).not.toBeInTheDocument());
});

const alertdialog = async () => within(await screen.findByRole("alertdialog"));

test("creating the sign-in asks first, says the old password stops working, and plans it", async () => {
  const fn = app(WITH(), { "POST /api/clusters/c1/kibana-login": [202, { operation_id: "lg2", change: {} }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Create sign-in" }));
  const dialog = await alertdialog();
  expect(dialog.getByText(/anyone using the old one can no longer sign in/)).toBeInTheDocument();
  expect(dialog.getByText(/ECM's own API key is not affected/)).toBeInTheDocument();
  expect(posted(fn, "/api/clusters/c1/kibana-login")).toEqual([]);                      // nothing is planned until it is confirmed
  await userEvent.click(dialog.getByRole("button", { name: "Plan it" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/lg2"));
  expect(posted(fn, "/api/clusters/c1/kibana-login")).toEqual([{}]);
});

test("with a sign-in set, the password stays hidden until it is asked for, and showing it is a POST that says it was recorded", async () => {
  const fn = app(WITH({ login: HAS_LOGIN }), { "POST /api/clusters/c1/kibana-login/reveal": [200, { username: "elastic", password: "Zq9-s3cret-value", reset_at: null }] });
  await panel();
  expect(screen.queryByText(/Zq9-s3cret-value/)).not.toBeInTheDocument();
  expect(screen.getByText(/Showing it is recorded in the audit log every time/)).toBeInTheDocument();
  expect(screen.queryByText("Nobody can sign in to this Kibana yet")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Show sign-in details" }));
  // The username and the password are separate blocks, so each copy button copies exactly its own value: no label and no other line.
  // What each copy button copies: its code block's text without the screen-reader prefix EUI brackets with these markers and strips on copy.
  const copied = Array.from(document.querySelectorAll(".euiCodeBlock"))
    .map((el) => (el.textContent ?? "").replace(/✄𐘗.*?✄𐘗/g, ""));
  expect(copied).toContain("Zq9-s3cret-value");                                          // the password, on its own
  expect(copied).toContain("elastic");                                                   // the username, on its own
  expect(copied.filter((t) => t.includes("Zq9-s3cret-value") && t !== "Zq9-s3cret-value")).toEqual([]);   // never with anything else
  expect(document.body.textContent).not.toMatch(/Password: |Username: /);
  expect(screen.getByText("Sign-in details (this view was recorded)")).toBeInTheDocument();
  expect(posted(fn, "/api/clusters/c1/kibana-login/reveal")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.queryByText(/Zq9-s3cret-value/)).not.toBeInTheDocument();
});

test("a refused reveal shows the reason and no password", async () => {
  app(WITH({ login: HAS_LOGIN }), { "POST /api/clusters/c1/kibana-login/reveal": [409, { detail: "ECM has not set a sign-in for this cluster's Kibana yet" }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Show sign-in details" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("has not set a sign-in");
  expect(screen.queryByText("Password")).not.toBeInTheDocument();
});

test("with a sign-in set, the button resets the password instead of creating one", async () => {
  const fn = app(WITH({ login: HAS_LOGIN }), { "POST /api/clusters/c1/kibana-login": [202, { operation_id: "lg3", change: {} }] });
  await panel();
  expect(screen.queryByRole("button", { name: "Create sign-in" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reset password" }));
  await userEvent.click((await alertdialog()).getByRole("button", { name: "Plan it" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/lg3"));
  expect(posted(fn, "/api/clusters/c1/kibana-login")).toEqual([{}]);
});

test("a failed attempt at the sign-in is linked from the notice", async () => {
  app(WITH({ login: { set: false, reset_at: null, last: { operation_id: "lg9", state: "failed", finished_at: null } } }));
  await panel();
  expect(screen.getByRole("link", { name: "open it" })).toHaveAttribute("href", "#/operations/lg9");
});

test("restarting Kibana asks first and then plans it", async () => {
  const fn = app(WITH(), { "POST /api/clusters/c1/restart-kibana": [202, { operation_id: "rs1", change: {} }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Restart Kibana" }));
  const dialog = await alertdialog();
  expect(dialog.getByText(/briefly disconnected; it holds no data/)).toBeInTheDocument();
  await userEvent.click(dialog.getByRole("button", { name: "Plan the restart" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rs1"));
  expect(posted(fn, "/api/clusters/c1/restart-kibana")).toEqual([{}]);
});

test("removing Kibana needs the cluster name typed and sends it", async () => {
  const fn = app(WITH(), { "POST /api/clusters/c1/remove-kibana": [202, { operation_id: "rm1", change: {} }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Remove Kibana" }));
  const dialog = await alertdialog();
  const go = dialog.getByRole("button", { name: "Plan the removal" });
  expect(go).toBeDisabled();
  expect(dialog.getByText(/saved objects stay in Elasticsearch, and ECM keeps the encryption keys/)).toBeInTheDocument();
  await userEvent.type(dialog.getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(go);
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rm1"));
  expect(posted(fn, "/api/clusters/c1/remove-kibana")).toEqual([{ confirm_name: "lab-d" }]);
});

test("a refusal when planning is shown and nothing navigates", async () => {
  app(WITH(), { "POST /api/clusters/c1/restart-kibana": [409, { detail: "an operation is already running" }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Restart Kibana" }));
  await userEvent.click((await alertdialog()).getByRole("button", { name: "Plan the restart" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already running");
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("a Kibana whose list of nodes is out of date says so and points at the restart", async () => {
  app(WITH({}, { hosts_out_of_date: true }));
  await panel();
  expect(screen.getByText("Kibana is using an out-of-date list of Elasticsearch nodes")).toBeInTheDocument();
  expect(screen.getByText(/restart it to bring the list up to date/)).toBeInTheDocument();
});

test("a Kibana that is up to date has no such notice", async () => {
  app(WITH());
  await panel();
  expect(screen.queryByText(/out-of-date list/)).not.toBeInTheDocument();
});

test("while something else runs, Kibana cannot be restarted, signed in to or removed", async () => {
  app({ ...WITH({ can_change: false }), busy_operation_id: "op9" });
  await panel();
  for (const name of ["Create sign-in", "Restart Kibana", "Remove Kibana"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});
