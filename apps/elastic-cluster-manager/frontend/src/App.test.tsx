import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { ConfirmAction } from "./ConfirmAction";
import { CreateClusterSteps } from "./CreateClusterSteps";
import { installReferenceReveals } from "./reveal";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/"; });

type Handler = (url: string, init?: RequestInit) => [number, unknown];
function mockFetch(handler: Handler) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const [status, body] = handler(url, init);
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const ME: [number, unknown] = [200, { username: "admin", role: "admin" }];
const CLUSTER = {
  id: "c1", name: "fixture-a", uuid: "aaaa", version: "9.5.6", health: "green", ownership: "discovered",
  nodes: 9, data_nodes: 6,
  infrastructure: { proxmox_hosts: ["pve1", "pve2"], verified_links: 8, total_nodes: 9 },
  storage: { total_bytes: 1024 ** 4, used_bytes: 1024 ** 3, used_pct: 40 },
  jvm_heap_used_pct: 55.5, jvm_heap_max_pct: 70, last_sync_at: null, last_sync_error: "boom",
};
const INFRA = {
  connections: [{ id: "p1", name: "pve-lab", api_url: "https://192.0.2.10:8006", last_sync_at: null, last_sync_error: null }],
  nodes: [], storages: [], templates: [],
  vms: [{ id: "v1", pve_node: "pve1", vmid: 301, name: "fxa-01", status: "running", cpu_cores: 4, memory_mb: 16384,
          ips: [{ ip: "192.0.2.21", source: "agent" }], es_cluster_id: "c1", es_link: "verified" }],
};

function route(map: Record<string, [number, unknown]>): Handler {
  return (url) => {
    if (url.endsWith("/me")) return ME;
    const hit = Object.keys(map).find((k) => url.endsWith(k));
    return hit ? map[hit] : [404, { detail: "not found" }];
  };
}

test("unauthenticated users see the login form", async () => {
  mockFetch(() => [401, { detail: "Not authenticated" }]);
  render(<App />);
  expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign in to manage your Elasticsearch clusters.");
  // The health key is part of the sign-in view and always pairs a dot with a text label.
  for (const name of ["Green", "Yellow", "Red", "Unknown"]) expect(screen.getByText(name)).toBeInTheDocument();
});

test("failed login shows an error, keeps the username and clears the password", async () => {
  mockFetch((url) => url.endsWith("/login") ? [401, { detail: "Invalid credentials" }] : [401, { detail: "x" }]);
  render(<App />);
  await userEvent.type(await screen.findByLabelText(/username/i), "admin");
  await userEvent.type(screen.getByLabelText(/^password/i), "nope");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Sign-in failed. Check the username and password, then try again.");
  expect(screen.getByLabelText(/username/i)).toHaveValue("admin");
  expect(screen.getByLabelText(/^password/i)).toHaveValue("");
});

test("dashboard summarises the last sync and lists clusters with health, links and sync errors", async () => {
  mockFetch(route({ "/api/clusters": [200, [CLUSTER]], "/api/infrastructure": [200, INFRA] }));
  render(<App />);
  const row = (await screen.findByRole("link", { name: "fixture-a" })).closest("tr")!;
  expect(within(row).getByText("green")).toBeInTheDocument();
  expect(within(row).getByText("9 (6)")).toBeInTheDocument();
  expect(within(row).getByText(/8\/9 nodes linked/)).toBeInTheDocument();
  expect(within(row).getByText("discovered")).toBeInTheDocument();
  expect(within(row).getByRole("alert")).toHaveTextContent("boom");
  // Stat tiles: clusters, nodes and VMs each carry a label.
  expect(screen.getByText("What the last sync saw.")).toBeInTheDocument();
  expect(screen.getByText("Registered with ECM")).toBeInTheDocument();
  expect(screen.getByText("Seen on Proxmox")).toBeInTheDocument();
});

test("dashboard empty state points at adding a connection", async () => {
  mockFetch(route({ "/api/clusters": [200, []], "/api/infrastructure": [200, { ...INFRA, vms: [] }] }));
  render(<App />);
  expect(await screen.findByText("No clusters registered")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Add connection" })).toHaveAttribute("href", "#/infrastructure");
});

test("dashboard error state names the cause and offers a retry", async () => {
  mockFetch(route({ "/api/clusters": [500, { detail: "database unavailable" }], "/api/infrastructure": [500, {}] }));
  render(<App />);
  expect(await screen.findByText("database unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("registering a cluster surfaces server errors and never repopulates the secret", async () => {
  window.location.hash = "#/infrastructure";
  mockFetch((url, init) => url.endsWith("/me") ? ME
    : init?.method === "POST" ? [502, { detail: "Could not reach cluster" }]
    : url.endsWith("/api/infrastructure") ? [200, INFRA] : [200, [CLUSTER]]);
  render(<App />);
  await screen.findByText("Where ECM reads from.");
  await userEvent.selectOptions(screen.getByLabelText("Connection type"), "elasticsearch");
  await userEvent.type(screen.getByLabelText(/endpoint url/i), "https://x:9200");
  await userEvent.type(screen.getByLabelText(/api key/i), "abcdefghij");
  await userEvent.click(screen.getByRole("button", { name: "Save connection" }));
  expect(await screen.findByText("Could not reach cluster")).toBeInTheDocument();
  expect(screen.getByLabelText(/api key/i)).toHaveValue("");
  expect(screen.getByLabelText(/endpoint url/i)).toHaveValue("https://x:9200");
});

test("skipping TLS verification shows the audited warning before saving", async () => {
  window.location.hash = "#/infrastructure";
  mockFetch(route({ "/api/infrastructure": [200, INFRA], "/api/clusters": [200, [CLUSTER]] }));
  render(<App />);
  await screen.findByText("Where ECM reads from.");
  expect(screen.queryByText(/recorded in the audit log\.$/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("switch", { name: "Skip TLS verification" }));
  expect(screen.getByText("Skipping verification is recorded in the audit log.")).toBeInTheDocument();
});

test("host usage shows 'Not available' instead of 0% of null when Proxmox sends none", async () => {
  window.location.hash = "#/infrastructure";
  const infra = { ...INFRA, nodes: [{ name: "pve1", status: "online", usage: {} }] };
  mockFetch(route({ "/api/infrastructure": [200, infra], "/api/clusters": [200, [CLUSTER]] }));
  render(<App />);
  expect((await screen.findAllByText("pve1")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(2);
  expect(screen.queryByText(/null/)).not.toBeInTheDocument();
});

test("infrastructure lists both connection panels with their state", async () => {
  window.location.hash = "#/infrastructure";
  mockFetch(route({ "/api/infrastructure": [200, INFRA], "/api/clusters": [200, [CLUSTER]] }));
  render(<App />);
  expect(await screen.findByText("pve-lab")).toBeInTheDocument();
  expect(screen.getByText("https://192.0.2.10:8006")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add Proxmox connection" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add Elasticsearch connection" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "verified" })).toHaveAttribute("href", "#/clusters/c1");
});

test("cluster detail separates the sources and shows link confidence", async () => {
  window.location.hash = "#/clusters/c1";
  const detail = { ...CLUSTER, last_sync_error: null,
    elasticsearch: { health: {}, shards: { by_state: {}, by_node: {}, unassigned: [] },
                     settings: { persistent: {}, transient: {} } },
    desired: { managed: false, note: "Not managed: this application holds no desired state for it yet." },
    node_list: [
      { id: "n1", name: "fxa-01", ip: "1.1.1.1", version: "9.5.6", roles: ["master"], heap_used_pct: 40,
        disk_total_bytes: 100, disk_avail_bytes: 60, shard_count: 0,
        link: { confidence: "verified", evidence: {}, vm: { pve_node: "pve1", vmid: 301, name: "fxa-01",
                cpu_cores: 4, memory_mb: 16384, disks: [] } } },
      { id: "n2", name: "fxa-07", ip: "1.1.1.7", version: "9.5.6", roles: [], heap_used_pct: 40,
        disk_total_bytes: 100, disk_avail_bytes: 60, shard_count: 0,
        link: { confidence: "unlinked", evidence: { reason: "ambiguous" }, vm: null } }] };
  mockFetch(route({ "/api/clusters/c1": [200, detail] }));
  render(<App />);
  expect(await screen.findByText("Inside this cluster.")).toBeInTheDocument();
  for (const card of ["Nodes", "Virtual machines", "Storage", "Last sync"])
    expect(screen.getByRole("heading", { name: card })).toBeInTheDocument();
  expect(screen.getByText(/Desired state:/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getAllByText("verified").length).toBeGreaterThan(0));
  expect(screen.getByText("ambiguous address")).toBeInTheDocument();
  expect(screen.getAllByText("coordinating only").length).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole("tab", { name: "Infrastructure" }));
  expect(await screen.findByText("pve1")).toBeInTheDocument();
});

test("cluster detail shows 'Not available' with a cause instead of a zero for missing storage", async () => {
  window.location.hash = "#/clusters/c1";
  const detail = { ...CLUSTER, last_sync_error: null, storage: { total_bytes: 0, used_bytes: 0, used_pct: null },
    elasticsearch: { health: {}, shards: { by_state: {}, by_node: {}, unassigned: [] }, settings: { persistent: {}, transient: {} } },
    desired: { managed: false, note: null }, node_list: [] };
  mockFetch(route({ "/api/clusters/c1": [200, detail] }));
  render(<App />);
  expect(await screen.findByText(/Elasticsearch did not report storage/)).toBeInTheDocument();
});

test("operations show state, phase and log lines from the API and can run the demo job", async () => {
  window.location.hash = "#/operations";
  const ops = [{ id: "op-1", kind: "demo", state: "running", phase: "provision", elapsed_seconds: 12, error: null }];
  const fn = mockFetch((url, init) => url.endsWith("/me") ? ME
    : init?.method === "POST" ? [200, {}] : [200, ops]);
  render(<App />);
  expect(await screen.findByRole("heading", { name: /demo/ })).toBeInTheDocument();
  expect(screen.getByLabelText("Operation log")).toHaveTextContent(/phase\s+provision/);
  await userEvent.click(screen.getByRole("button", { name: "Run demo job" }));
  await waitFor(() => expect(fn).toHaveBeenCalledWith("/api/operations/demo", expect.objectContaining({ method: "POST" })));
});

test("help answers open and close independently", async () => {
  window.location.hash = "#/help";
  mockFetch(route({}));
  render(<App />);
  const q = await screen.findByRole("button", { name: /Does ECM change my clusters or VMs\?/ });
  expect(q).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(q);
  expect(q).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText(/Discovery only reads/)).toBeInTheDocument();
});

test("the header marks the current page and the theme toggle persists the choice", async () => {
  window.location.hash = "#/help";
  mockFetch(route({}));
  render(<App />);
  const help = await screen.findByRole("link", { name: "Help" });
  expect(help).toHaveAttribute("aria-current", "page");
  await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
  expect(localStorage.getItem("ecm.theme")).toBe("dark");
  expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
});

test("a destructive confirmation names the resource and stays disabled until it is typed", async () => {
  const onConfirm = vi.fn();
  render(<ConfirmAction action="Delete" resource="fixture-a" destructive onConfirm={onConfirm} onCancel={() => {}} />);
  const confirm = screen.getByRole("button", { name: "Delete" });
  expect(screen.getByText("Delete fixture-a?")).toBeInTheDocument();
  expect(confirm).toBeDisabled();
  await userEvent.type(screen.getByLabelText(/Type fixture-a to confirm/), "fixture-a");
  expect(confirm).toBeEnabled();
  await userEvent.click(confirm);
  expect(onConfirm).toHaveBeenCalled();
});

test("the wizard keeps entered values when moving between steps and never calls the API", async () => {
  const fn = mockFetch(() => [200, {}]);
  render(<CreateClusterSteps />);
  await userEvent.type(screen.getByLabelText("Cluster name"), "lab-b");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "/ Placement" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByLabelText("Cluster name")).toHaveValue("lab-b");
  expect(screen.getByText("lab-b", { selector: "dd" })).toBeInTheDocument();
  expect(fn).not.toHaveBeenCalled();
});

test("reveals leave content visible when animation or observers are unavailable", () => {
  const host = document.createElement("div");
  host.innerHTML = '<div data-reveal="rise">a</div><div data-reveal="media">b</div>';
  document.body.append(host);
  const stop = installReferenceReveals(host);
  host.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => expect(el.dataset.revealPlayed).toBe("true"));
  stop();
  host.remove();
});
