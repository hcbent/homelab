import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";

afterEach(() => vi.restoreAllMocks());
beforeEach(() => { window.location.hash = "#/"; });

type Handler = (url: string, init?: RequestInit) => [number, unknown];
function mockFetch(handler: Handler) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const [status, body] = handler(url, init);
    return new Response(JSON.stringify(body), { status });
  }));
}

const ME: [number, unknown] = [200, { username: "admin", role: "admin" }];
const CLUSTER = {
  id: "c1", name: "fixture-a", uuid: "aaaa", version: "9.5.6", health: "green", ownership: "discovered",
  nodes: 9, data_nodes: 6,
  infrastructure: { proxmox_hosts: ["pve1", "pve2"], verified_links: 8, total_nodes: 9 },
  storage: { total_bytes: 1024 ** 4, used_bytes: 1024 ** 3, used_pct: 40 },
  jvm_heap_used_pct: 55.5, jvm_heap_max_pct: 70, last_sync_at: null, last_sync_error: "boom",
};

test("unauthenticated users see the login form", async () => {
  mockFetch(() => [401, { detail: "Not authenticated" }]);
  render(<App />);
  expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
});

test("failed login shows an error", async () => {
  mockFetch((url) => url.endsWith("/login") ? [401, { detail: "Invalid credentials" }] : [401, { detail: "x" }]);
  render(<App />);
  await userEvent.type(await screen.findByLabelText(/username/i), "admin");
  await userEvent.type(screen.getByLabelText(/password/i), "nope");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
});

test("dashboard lists clusters with health, links and sync errors", async () => {
  mockFetch((url) => url.endsWith("/me") ? ME : [200, [CLUSTER]]);
  render(<App />);
  const row = (await screen.findByRole("link", { name: "fixture-a" })).closest("tr")!;
  expect(within(row).getByText("green")).toBeInTheDocument();
  expect(within(row).getByText("9 (6)")).toBeInTheDocument();
  expect(within(row).getByText(/8\/9 nodes linked/)).toBeInTheDocument();
  expect(within(row).getByText("discovered")).toBeInTheDocument();
  expect(within(row).getByRole("alert")).toHaveTextContent("boom");
});

test("registering a cluster surfaces server errors", async () => {
  mockFetch((url, init) => url.endsWith("/me") ? ME
    : init?.method === "POST" ? [502, { detail: "Could not reach cluster" }] : [200, []]);
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Register cluster" }));
  await userEvent.type(screen.getByLabelText(/endpoint url/i), "https://x:9200");
  await userEvent.type(screen.getByLabelText(/api key/i), "abcdefghij");
  await userEvent.click(screen.getByRole("button", { name: "Register" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach cluster");
});

test("cluster detail separates the three sources and shows link confidence", async () => {
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
  mockFetch((url) => url.endsWith("/me") ? ME : [200, detail]);
  render(<App />);
  expect(await screen.findByText("Elasticsearch reports")).toBeInTheDocument();
  expect(screen.getByText("Proxmox reports")).toBeInTheDocument();
  expect(screen.getByText("Desired state")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("verified")).toBeInTheDocument());
  expect(screen.getByText("ambiguous address")).toBeInTheDocument();
  expect(screen.getByText("coordinating only")).toBeInTheDocument();
});
