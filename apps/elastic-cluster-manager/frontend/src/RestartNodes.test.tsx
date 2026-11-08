import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const NODE_ROLES = {
  "lab-d-01": { roles: ["master"], master_eligible: true, holds_data: false, host: "pve1" },
  "lab-d-02": { roles: ["master"], master_eligible: true, holds_data: false, host: "pve2" },
  "lab-d-03": { roles: ["data"], master_eligible: false, holds_data: true, host: "pve3" },
  "lab-d-04": { roles: ["data"], master_eligible: false, holds_data: true, host: "pve1" },
  "lab-d-05": { roles: [], master_eligible: false, holds_data: false, host: "pve2" },
};
const IN = { machine: true, in_cluster: true, vm_status: "running" };
const NODE_STATE = {
  "lab-d-01": IN, "lab-d-02": IN, "lab-d-03": IN, "lab-d-04": IN, "lab-d-05": IN,
};
const LIFE = { managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: true,
  can_remove: false, data_disks: {}, can_change: true, sizes: {}, node_roles: NODE_ROLES, node_state: NODE_STATE };
const INFRA = { connections: [], nodes: [], storages: [], templates: [], vms: [] };
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
const panel = () => screen.findByRole("heading", { name: "Restart nodes" });
const plan = () => screen.getByRole("button", { name: "Plan the restart" });
const inPanel = async () => {
  const heading = await panel();
  return within(heading.closest(".ecm-lifecycle") as HTMLElement);
};

test("the panel explains the order and the use, lists every node with its role, and plans nothing until a node is chosen", async () => {
  app(LIFE);
  const p = await inPanel();
  expect(p.getByText("Nodes are restarted one at a time, each briefly out of the cluster")).toBeInTheDocument();
  expect(p.getByText(/apply a configuration change that is waiting for a restart/)).toBeInTheDocument();
  expect(p.getByLabelText("lab-d-01: master (master-eligible)")).toBeInTheDocument();
  expect(p.getByLabelText("lab-d-05: coordinating only")).toBeInTheDocument();
  expect(plan()).toBeDisabled();
});

test("a node with the default roles reads as all roles, not a line of eleven names", async () => {
  const everything = ["data", "data_cold", "data_content", "data_frozen", "data_hot", "data_warm", "ingest", "master", "ml", "remote_cluster_client", "transform"];
  app({ ...LIFE, node_roles: { ...NODE_ROLES, "lab-d-04": { roles: everything, master_eligible: true, holds_data: true, host: "pve1" } } });
  const p = await inPanel();
  expect(p.getByLabelText("lab-d-04: all roles (master-eligible)")).toBeInTheDocument();
});

test("the chosen nodes are posted after a confirmation that says nothing changes yet", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/restart-nodes": [202, { operation_id: "rs1", change: {} }] });
  const p = await inPanel();
  await userEvent.click(p.getByLabelText(/lab-d-04/));
  await userEvent.click(p.getByLabelText(/lab-d-01/));
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/plan the order for 2 nodes and show you the plan. This step changes nothing/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the restart" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rs1"));
  expect(posted(fn, "/api/clusters/c1/restart-nodes")).toEqual([{ nodes: ["lab-d-01", "lab-d-04"] }]);
});

test("nodes with a change waiting for a restart are marked, and one button plans exactly those", async () => {
  const fn = app({ ...LIFE, pending_restart: ["lab-d-02", "lab-d-04"] },
    { "POST /api/clusters/c1/restart-nodes": [202, { operation_id: "rs3", change: {} }] });
  const p = await inPanel();
  expect(p.getByText("lab-d-02, lab-d-04 have a configuration change waiting for a restart")).toBeInTheDocument();
  expect(p.getByLabelText("lab-d-02: master (master-eligible) (configuration waiting for a restart)")).toBeInTheDocument();
  expect(p.getByLabelText("lab-d-01: master (master-eligible)")).toBeInTheDocument();                // not waiting: no mark
  await userEvent.click(p.getByRole("button", { name: "Restart the 2 nodes waiting for a restart" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rs3"));
  expect(posted(fn, "/api/clusters/c1/restart-nodes")).toEqual([{ pending: true }]);                 // no node list: ECM works it out
});

test("with nothing waiting there is no banner and no waiting button", async () => {
  app({ ...LIFE, pending_restart: [] });
  const p = await inPanel();
  expect(p.queryByText(/(has|have) a configuration change waiting for a restart/)).not.toBeInTheDocument();
  expect(p.queryByRole("button", { name: /waiting for a restart/ })).not.toBeInTheDocument();
});

test("select every node chooses them all, and clear empties the choice", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/restart-nodes": [202, { operation_id: "rs2", change: {} }] });
  const p = await inPanel();
  await userEvent.click(p.getByRole("button", { name: "Select every node" }));
  expect(p.getByLabelText(/lab-d-03/)).toBeChecked();
  await userEvent.click(p.getByRole("button", { name: "Clear" }));
  expect(p.getByLabelText(/lab-d-03/)).not.toBeChecked();
  await userEvent.click(p.getByRole("button", { name: "Select every node" }));
  await userEvent.click(plan());
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Plan the restart" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rs2"));
  expect((posted(fn, "/api/clusters/c1/restart-nodes")[0] as { nodes: string[] }).nodes).toHaveLength(5);
});

test("a node that is down says what will happen to it, and a lost node cannot be chosen", async () => {
  app({ ...LIFE, node_state: { ...NODE_STATE,
    "lab-d-03": { machine: true, in_cluster: false, vm_status: "stopped" },
    "lab-d-04": { machine: true, in_cluster: false, vm_status: "running" },
    "lab-d-05": { machine: false, in_cluster: false, vm_status: null } } });
  const p = await inPanel();
  expect(p.getByLabelText(/lab-d-03: data \(not in the cluster, its machine is stopped: it will be started first\)/)).toBeInTheDocument();
  expect(p.getByLabelText(/lab-d-04: data \(not in the cluster, its machine is running: it will be restarted first\)/)).toBeInTheDocument();
  const lost = p.getByLabelText(/lab-d-05: coordinating only \(lost: rebuild or forget it under Recovery\)/);
  expect(lost).toBeDisabled();
  await userEvent.click(p.getByRole("button", { name: "Select every node" }));
  expect(lost).not.toBeChecked();                                                      // a lost node is never part of "every node"
});

test("a refusal from ECM is shown with its reason and nothing navigates", async () => {
  app(LIFE, { "POST /api/clusters/c1/restart-nodes": [409, { detail: "the cluster is yellow, and a node is restarted only from a green cluster" }] });
  const p = await inPanel();
  await userEvent.click(p.getByLabelText(/lab-d-04/));
  await userEvent.click(plan());
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Plan the restart" }));
  expect(await screen.findByText(/a node is restarted only from a green cluster/)).toBeInTheDocument();
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("while another operation runs the form is replaced by a link to it", async () => {
  app({ ...LIFE, busy_operation_id: "op9" });
  const p = await inPanel();
  expect(p.getByRole("link", { name: "Open it" })).toHaveAttribute("href", "#/operations/op9");
  expect(screen.queryByRole("button", { name: "Plan the restart" })).not.toBeInTheDocument();
});

test("no two checkboxes on the cluster page share a DOM id, so a label always toggles its own panel's box", async () => {
  // Every panel that lists the nodes is on the page at once: Remove, Restart, Resize and Grow disks (Recovery when a node is lost).
  const sizes = Object.fromEntries(Object.keys(NODE_ROLES).map((n) => [n, { cores: 2, ram_mb: 4096 }]));
  const lifecycle = { ...LIFE, sizes, data_disks: { "lab-d-03": 100, "lab-d-04": 100 },
    node_state: { ...NODE_STATE, "lab-d-05": { machine: false, in_cluster: false, vm_status: null } } };
  app(lifecycle);
  await panel();
  await screen.findByRole("heading", { name: "Resize nodes" });
  await screen.findByRole("heading", { name: "Recovery" });
  const found = Array.from(document.querySelectorAll<HTMLInputElement>("input[type=checkbox]")).map((c) => c.id);
  expect(found.length).toBeGreaterThan(10);
  expect(new Set(found).size).toBe(found.length);
  // and clicking a label in the Restart panel changes that panel's box and no other
  const mine = within((await panel()).closest(".ecm-lifecycle") as HTMLElement);
  await userEvent.click(mine.getByLabelText(/lab-d-04/));
  expect(mine.getByLabelText(/lab-d-04/)).toBeChecked();
  const remove = within(screen.getByRole("heading", { name: "Remove nodes" }).closest(".ecm-lifecycle") as HTMLElement);
  expect(remove.getByLabelText(/lab-d-04/)).not.toBeChecked();
});
