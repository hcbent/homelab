import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const SIZES = {
  "lab-d-01": { cores: 2, ram_mb: 4096 }, "lab-d-02": { cores: 2, ram_mb: 4096 }, "lab-d-03": { cores: 2, ram_mb: 4096 },
  "lab-d-04": { cores: 4, ram_mb: 8192 },
};
const LIFE = { managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: true,
  can_remove: false, data_disks: { "lab-d-04": 100 }, can_change: true, sizes: SIZES };
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
const panel = () => screen.findByRole("heading", { name: "Add nodes" });
const plan = () => screen.getByRole("button", { name: "Plan adding nodes" });
const confirm = async () => {
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan adding nodes" }));
};

test("the panel explains what it does and the master spread rule, and offers the roles as a multi-select", async () => {
  app(LIFE);
  await panel();
  expect(screen.getByText(/Only the new nodes are configured and started/)).toBeInTheDocument();
  expect(screen.getByText(/adding one more is refused, because four need four hosts; adding two at once is\s+allowed/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Roles")).not.toBeInTheDocument();                  // the dropdown appears for "Choose the roles"
  await userEvent.click(screen.getByLabelText(/Choose the roles/));
  expect(screen.getByLabelText("Roles")).toBeInTheDocument();
});

test("default roles send no role list, and the count and optional sizes are sent as asked", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/add-nodes": [202, { operation_id: "ad1", change: {} }] });
  await panel();
  const count = screen.getByLabelText("How many");
  await userEvent.clear(count);
  await userEvent.type(count, "2");
  await userEvent.type(screen.getByLabelText(/Cores \(leave empty to copy/), "8");
  await userEvent.type(screen.getByLabelText(/RAM, GiB/), "16");
  await userEvent.type(screen.getByLabelText(/Data disk, GB/), "200");
  await userEvent.selectOptions(screen.getByLabelText("Proxmox host"), "pve2");
  await confirm();
  await waitFor(() => expect(window.location.hash).toBe("#/operations/ad1"));
  expect(posted(fn, "/api/clusters/c1/add-nodes")).toEqual([
    { count: 2, cores: 8, ram_mb: 16384, data_disk_gb: 200, pve_node: "pve2" }]);
});

test("coordinating only sends an empty role list and has no data disk", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/add-nodes": [202, { operation_id: "ad2", change: {} }] });
  await panel();
  await userEvent.click(screen.getByLabelText(/Coordinating only/));
  expect(screen.getByLabelText(/Data disk, GB/)).toBeDisabled();
  await confirm();
  await waitFor(() => expect(window.location.hash).toBe("#/operations/ad2"));
  expect(posted(fn, "/api/clusters/c1/add-nodes")).toEqual([{ count: 1, roles: [] }]);
});

test("chosen roles are sent as a list, and a data disk is offered only when a role holds data", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/add-nodes": [202, { operation_id: "ad3", change: {} }] });
  await panel();
  await userEvent.click(screen.getByLabelText(/Choose the roles/));
  expect(plan()).toBeDisabled();                                                     // nothing chosen yet
  const combo = screen.getByLabelText("Roles");
  await userEvent.click(combo);
  await userEvent.type(combo, "ml");
  await userEvent.click(await screen.findByRole("option", { name: "ml" }));
  expect(plan()).toBeEnabled();
  expect(screen.getByLabelText(/Data disk, GB/)).toBeDisabled();                     // ml holds no data
  await userEvent.click(combo);
  await userEvent.type(combo, "data_hot");
  await userEvent.click(await screen.findByRole("option", { name: "data_hot" }));
  expect(screen.getByLabelText(/Data disk, GB/)).toBeEnabled();                      // now one does
  await confirm();
  await waitFor(() => expect(window.location.hash).toBe("#/operations/ad3"));
  expect(posted(fn, "/api/clusters/c1/add-nodes")).toEqual([{ count: 1, roles: ["ml", "data_hot"] }]);
});

test("voting_only without master is caught, and the count is bounded", async () => {
  app(LIFE);
  await panel();
  await userEvent.click(screen.getByLabelText(/Choose the roles/));
  const combo = screen.getByLabelText("Roles");
  await userEvent.click(combo);
  await userEvent.type(combo, "voting_only");
  await userEvent.click(await screen.findByRole("option", { name: "voting_only" }));
  expect(await screen.findByText("voting_only needs the master role too.")).toBeInTheDocument();
  expect(plan()).toBeDisabled();
  const count = screen.getByLabelText("How many");
  await userEvent.clear(count);
  await userEvent.type(count, "11");
  expect(await screen.findByText("Add between 1 and 10 nodes at a time.")).toBeInTheDocument();
});

test("a refusal from the API is shown and the page stays", async () => {
  app(LIFE, { "POST /api/clusters/c1/add-nodes": [409, { detail: "the nodes cannot be placed: host 'pve3' would hold 2 of 4 master-eligible nodes" }] });
  await panel();
  await confirm();
  expect(await screen.findByText(/would hold 2 of 4 master-eligible nodes/)).toBeInTheDocument();
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("a single-node cluster is not offered the panel's form, and a busy cluster shows a link", async () => {
  app({ ...LIFE, sizes: { "solo-01": { cores: 2, ram_mb: 4096 } } });
  await panel();
  expect(screen.getByText(/single-node cluster is started in a mode that cannot take other nodes/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Plan adding nodes" })).not.toBeInTheDocument();
});

test("a busy cluster shows a link to the running operation instead of the form", async () => {
  app({ ...LIFE, busy_operation_id: "op9", can_change: false });
  await panel();
  expect(screen.queryByLabelText("How many")).not.toBeInTheDocument();
  screen.getAllByRole("link", { name: "Open it" }).forEach((l) => expect(l).toHaveAttribute("href", "#/operations/op9"));
});
