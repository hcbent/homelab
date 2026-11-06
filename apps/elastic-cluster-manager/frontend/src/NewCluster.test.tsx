import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { EMPTY_FORM, NewCluster, toRequest, topologyText, validate } from "./NewCluster";
import { mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/new"; });

const DIGEST = "a".repeat(64);
const VERSIONS = { versions: ["9.6.0", "9.5.6", "8.19.4"] };
const INFRA = {
  connections: [{ id: "p1", name: "pve-lab", api_url: "https://192.0.2.10:8006", last_sync_at: null, last_sync_error: null }],
  nodes: [], vms: [],
  storages: [{ node: "pve1", name: "tank", type: "zfspool", shared: true, total: 1, used: 0, avail: 1 }],
  templates: [{ id: "t1", pve_node: "pve1", vmid: 8000, name: "ubuntu-25.04", status: "stopped", cpu_cores: 2,
    memory_mb: 2048, ips: [], es_cluster_id: null, es_link: null }],
};
const PROFILES = [{ id: "n1", name: "default", bridge: "vmbr0", vlan: null, cidr: "192.168.10.0/24",
  gateway: "192.168.10.1", dns: ["192.168.10.1"], search_domain: null, range_start: "192.168.10.110",
  range_end: "192.168.10.149", dhcp_start: null, dhcp_end: null, pool_size: 40, in_use_in_range: [] }];
const PLAN = {
  cluster_id: "c1", operation_id: "op1", dry_run: true, warnings: ["pve1 is over-committed"],
  nodes: ["lab-c-01", "lab-c-02", "lab-c-03"].map((name, i) => ({
    name, host: `pve${i + 1}`, address: `192.168.10.${113 + i}`, vm_id: 503 + i })),
};
const DRY_OP = {
  id: "op1", kind: "tf.create", state: "succeeded", phase: null, error: null, elapsed_seconds: 8, dry_run: true,
  progress: { done: 3, total: 3 }, approval: null, result: null, steps: [], logs: [],
  plan: { digest: DIGEST, approvable: false, summary: { adds: 3, updates: 0, deletes: 0,
    configure: "install elasticsearch 9.6.0 on 3 nodes and start the cluster" } },
};
const base = (over: Record<string, [number, unknown]> = {}) => table({
  "GET /api/versions": [200, VERSIONS], "GET /api/infrastructure": [200, INFRA],
  "GET /api/network-profiles": [200, PROFILES], "POST /api/clusters": [202, PLAN],
  "GET /api/operations/op1": [200, DRY_OP], ...over,
});

const next = () => userEvent.click(screen.getByRole("button", { name: "Continue" }));
const continueButton = () => screen.getByRole("button", { name: "Continue" });
async function fill(label: string, value: string) {
  const input = screen.getByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, value);
}
async function start(name = "lab-c") {
  render(<NewCluster />);
  await waitFor(() => expect(screen.getByLabelText("Elasticsearch version")).toHaveValue("9.6.0"));
  await userEvent.type(screen.getByLabelText("Cluster name"), name);
}
async function toReview() {
  for (const heading of ["/ Topology", "/ Sizing", "/ Infrastructure", "/ Review"]) {
    await next();
    await screen.findByRole("heading", { name: heading });
  }
}

test("it walks every step, sends a dry run with exactly the choices made, then plans the build", async () => {
  const fn = mockFetch(base());
  await start();
  expect(screen.getByLabelText("Elasticsearch version")).toHaveValue("9.6.0");        // newest is preselected
  await next();
  await userEvent.click(await screen.findByLabelText(/Dedicated masters/));
  await fill("Data nodes", "4");
  await fill("Coordinating nodes", "1");
  await next();
  await fill("Cores per node", "8");
  await next();
  await waitFor(() => expect(screen.getByLabelText("Network profile")).toHaveValue("default"));
  await fill("CPU type", "x86-64-v2-AES");
  await next();

  expect(await screen.findByText("lab-c-01")).toBeInTheDocument();
  expect(posted(fn, "/api/clusters")).toEqual([{
    name: "lab-c", version: "9.6.0", preset: "dedicated_masters", dry_run: true, data_nodes: 4, coordinating_nodes: 1,
    sizing: { cores: 8 }, proxmox_connection_id: "p1", network_profile: "default", cpu_type: "x86-64-v2-AES",
  }]);
  const table = screen.getByRole("table");                              // the only table on this step
  expect(within(table).getByText("pve2")).toBeInTheDocument();
  expect(within(table).getByText("192.168.10.115")).toBeInTheDocument();
  expect(screen.getByText("pve1 is over-committed")).toBeInTheDocument();             // a warning is shown, not hidden
  expect(await screen.findByText("Create 3 virtual machines")).toBeInTheDocument();
  expect(screen.getByText("Install elasticsearch 9.6.0 on 3 nodes and start the cluster")).toBeInTheDocument();

  await waitFor(() => expect(continueButton()).toBeEnabled());
  await next();
  await userEvent.click(await screen.findByRole("button", { name: "Plan the build" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/op1"));
  expect(posted(fn, "/api/clusters")[1]).toMatchObject({ name: "lab-c", dry_run: false });
});

test("a refusal is shown with its reason, Continue stays off, and only changed values are sent", async () => {
  const reason = "host 'pve3' would hold 2 of 3 master-eligible nodes, and losing it would break the master quorum. "
    + "pve1 could not take one: not enough free RAM";
  const fn = mockFetch(base({ "POST /api/clusters": [422, { detail: reason }] }));
  await start();
  await toReview();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("ECM cannot plan this cluster");
  expect(alert).toHaveTextContent("pve1 could not take one: not enough free RAM");
  expect(within(alert).getByRole("link", { name: "Infrastructure" })).toHaveAttribute("href", "#/infrastructure");
  expect(continueButton()).toBeDisabled();
  expect(posted(fn, "/api/clusters")[0]).toEqual({
    name: "lab-c", version: "9.6.0", preset: "three_node", dry_run: true,
    proxmox_connection_id: "p1", network_profile: "default",              // no sizing, no counts: nothing was changed
  });
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(posted(fn, "/api/clusters")).toHaveLength(2));
});

test("a bad name or size is explained and blocks Continue until it is fixed", async () => {
  mockFetch(base());
  await start("Lab_B");
  await userEvent.tab();
  expect(await screen.findByText(/Use 2 to 40 lowercase letters/)).toBeInTheDocument();
  expect(continueButton()).toBeDisabled();
  await userEvent.clear(screen.getByLabelText("Cluster name"));
  await userEvent.type(screen.getByLabelText("Cluster name"), "lab-c");
  expect(continueButton()).toBeEnabled();
  await next();
  await next();
  await screen.findByRole("heading", { name: "/ Sizing" });
  await fill("Cores per node", "0");
  await userEvent.tab();
  expect(await screen.findByText("Cores must be between 1 and 64.")).toBeInTheDocument();
  expect(continueButton()).toBeDisabled();
  await fill("Cores per node", "4");
  expect(continueButton()).toBeEnabled();
});

test("when the version list cannot load, a typed version is accepted and the reason is shown", async () => {
  const fn = mockFetch(base({ "GET /api/versions": [503, { detail: "could not fetch the version list" }] }));
  render(<NewCluster />);
  expect(await screen.findByText("Could not load the list of versions")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Cluster name"), "lab-c");
  expect(continueButton()).toBeDisabled();                                // a version is still required
  await userEvent.type(screen.getByLabelText("Elasticsearch version"), "9.5.6");
  expect(continueButton()).toBeEnabled();
  await toReview();
  await waitFor(() => expect(posted(fn, "/api/clusters")[0]).toMatchObject({ version: "9.5.6" }));
});

test("changing a choice after the review plans a fresh dry run", async () => {
  const fn = mockFetch(base());
  await start();
  await toReview();
  await waitFor(() => expect(continueButton()).toBeEnabled());
  expect(posted(fn, "/api/clusters")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  await screen.findByRole("heading", { name: "/ Sizing" });
  await fill("RAM per node (GiB)", "16");
  await next();
  await next();
  await screen.findByRole("heading", { name: "/ Review" });
  await waitFor(() => expect(posted(fn, "/api/clusters")).toHaveLength(2));
  expect(posted(fn, "/api/clusters")[1]).toMatchObject({ sizing: { ram_mb: 16384 } });
});

test("going back and forward without changing anything does not plan again", async () => {
  const fn = mockFetch(base());
  await start();
  await toReview();
  await waitFor(() => expect(continueButton()).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  await next();
  await screen.findByRole("heading", { name: "/ Review" });
  expect(posted(fn, "/api/clusters")).toHaveLength(1);
});

test("a refused build stays on the page with the reason", async () => {
  let post = 0;
  mockFetch((url, init) => {
    if (url === "/api/clusters" && init?.method === "POST") {
      post += 1;
      return post === 1 ? [202, PLAN] : [409, { detail: "'lab-c' has an operation in progress; finish or cancel it first" }];
    }
    return base()(url, init);
  });
  await start();
  await toReview();
  await waitFor(() => expect(continueButton()).toBeEnabled());
  await next();
  await userEvent.click(await screen.findByRole("button", { name: "Plan the build" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("has an operation in progress");
  expect(window.location.hash).toBe("#/new");
});

test("a failed dry run's own error is shown and the review cannot continue", async () => {
  mockFetch(base({ "GET /api/operations/op1": [200, { ...DRY_OP, state: "failed", plan: null,
    error: "the token Terraform uses is missing rights this operation needs: VM.Allocate on /pool/ecm" }] }));
  await start();
  await toReview();
  expect(await screen.findByText("The plan could not be made")).toBeInTheDocument();
  expect(screen.getByText(/missing rights this operation needs/)).toBeInTheDocument();
  expect(continueButton()).toBeDisabled();
});

test("the wizard opens from the hash, the dashboard links to it, and Clusters stays highlighted", async () => {
  mockFetch(table({
    "GET /api/auth/me": [200, { username: "admin", role: "admin" }], "GET /api/versions": [200, VERSIONS],
    "GET /api/infrastructure": [200, INFRA], "GET /api/network-profiles": [200, PROFILES] }));
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Create a cluster, one decision at a time." })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Clusters" })).toHaveAttribute("aria-current", "page");
});

test("the dashboard has a Create cluster button that opens the wizard", async () => {
  window.location.hash = "#/";
  mockFetch(table({
    "GET /api/auth/me": [200, { username: "admin", role: "admin" }], "GET /api/clusters": [200, []],
    "GET /api/infrastructure": [200, INFRA] }));
  render(<App />);
  expect(await screen.findByRole("link", { name: "Create cluster" })).toHaveAttribute("href", "#/new");
});

test("validate and toRequest handle each topology and send only what was changed", () => {
  const ok = { ...EMPTY_FORM, name: "lab-c", version: "9.5.6" };
  expect(validate(ok)).toEqual({});
  expect(toRequest(ok, true)).toEqual({ name: "lab-c", version: "9.5.6", preset: "three_node", dry_run: true });
  expect(toRequest({ ...ok, preset: "dedicated_masters", dataNodes: "2", coordinating: "1" }, false))
    .toMatchObject({ preset: "dedicated_masters", data_nodes: 2, coordinating_nodes: 1, dry_run: false });
  expect(toRequest({ ...ok, cores: "2", ramGb: "4", osDisk: "20", dataDisk: "50" }, true).sizing)
    .toEqual({ cores: 2, ram_mb: 4096, os_disk_gb: 20, data_disk_gb: 50 });
  expect(toRequest({ ...ok, template: "8000", datastore: "tank", pool: "ecm" }, true))
    .toMatchObject({ template_vmid: 8000, datastore: "tank", pool_id: "ecm" });
  expect(validate({ ...ok, preset: "dedicated_masters", dataNodes: "0" }).dataNodes).toMatch(/between 1 and 40/);
  expect(validate({ ...ok, preset: "three_node", dataNodes: "0" }).dataNodes).toBeUndefined();   // not used here
  expect(validate({ ...ok, ramGb: "1" }).ramGb).toMatch(/between 2 and 512/);
  expect(validate({ ...ok, name: "a" }).name).toBeDefined();
  expect(validate({ ...ok, version: "9.5" }).version).toBe("A version looks like 9.5.6.");
  expect(validate({ ...ok, pool: "bad pool" }).pool).toBeDefined();
  expect(topologyText({ ...ok, preset: "dedicated_masters", dataNodes: "3", coordinating: "2" }))
    .toBe("3 masters + 3 data + 2 coordinating");
});

test("steps that have not been reached cannot be jumped to from the strip", async () => {
  mockFetch(base());
  await start();
  const strip = document.querySelector(".ecm-wizard__strip") as HTMLElement;
  const buttons = within(strip).getAllByRole("button");
  expect(buttons).toHaveLength(6);
  expect(buttons[0]).toBeEnabled();
  expect(buttons.slice(1).every((b) => b.hasAttribute("disabled"))).toBe(true);
  await next();
  await screen.findByRole("heading", { name: "/ Topology" });
  expect(within(strip).getAllByRole("button")[1]).toBeEnabled();                      // reached now
  expect(within(strip).getAllByRole("button")[2]).toBeDisabled();
});
