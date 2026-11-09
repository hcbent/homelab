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
  caddy_snippet: SNIPPET };
const NONE = { machines: [], can_add: true, ca_available: true, last_add: null };
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
  app({ ...LIFE, kibana: { machines: [MACHINE], can_add: false, ca_available: true,
    last_add: { operation_id: "k1", state: "succeeded", finished_at: "2026-11-09T18:00:00Z" } } });
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

test("the panel says plainly that nobody can sign in yet, because that part is not built", async () => {
  app({ ...LIFE, kibana: { machines: [MACHINE], can_add: false, ca_available: true, last_add: null } });
  await panel();
  expect(screen.getByText("Nobody can sign in to this Kibana yet")).toBeInTheDocument();
  expect(screen.getByText(/has not been built/)).toBeInTheDocument();
});

test("a Kibana added without a name has no snippet, and a failed add points at Retry", async () => {
  app({ ...LIFE, kibana: { machines: [{ ...MACHINE, public_name: null, public_url: null, caddy_snippet: null }], can_add: false,
    ca_available: false, last_add: { operation_id: "k3", state: "failed", finished_at: null } } });
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
