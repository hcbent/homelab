import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const NODE_STATE = {
  "lab-d-01": { machine: true, in_cluster: true }, "lab-d-02": { machine: true, in_cluster: true },
  "lab-d-03": { machine: true, in_cluster: true },
  "lab-d-04": { machine: false, in_cluster: false }, "lab-d-05": { machine: false, in_cluster: false },
};
const LIFE = { managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: true,
  can_remove: false, data_disks: {}, can_change: true, sizes: {}, node_roles: {}, node_state: NODE_STATE };
const INFRA = { connections: [], nodes: [{ name: "pve1", status: "online", usage: {} }, { name: "pve2", status: "online", usage: {} }],
  storages: [], templates: [], vms: [] };
const detail = (lifecycle: unknown) => ({
  id: "c1", name: "lab-d", uuid: null, version: "9.5.6", health: "yellow", ownership: "managed", nodes: 0, data_nodes: 0,
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
const panel = () => screen.findByRole("heading", { name: "Recovery" });

test("a cluster with every node present shows no Recovery panel", async () => {
  app({ ...LIFE, node_state: { "lab-d-01": { machine: true, in_cluster: true } } });
  await screen.findByRole("heading", { name: "Tear down or remove" });      // the page has loaded
  expect(screen.queryByRole("heading", { name: "Recovery" })).not.toBeInTheDocument();
});

test("the panel names the lost nodes, explains rebuild and forget, and says a red cluster is dealt with by hand", async () => {
  app(LIFE);
  await panel();
  expect(screen.getByText("2 nodes are lost: lab-d-04, lab-d-05")).toBeInTheDocument();
  expect(screen.getByText(/a red cluster has lost data, which has to be dealt with by hand first/)).toBeInTheDocument();
  expect(screen.getByLabelText("lab-d-04")).toBeChecked();
  expect(screen.getByRole("button", { name: "Plan the rebuild" })).toBeEnabled();
});

test("a rebuild posts the chosen nodes and the host only when one is chosen", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/rebuild-nodes": [202, { operation_id: "rb1", change: {} }] });
  await panel();
  await userEvent.click(screen.getByLabelText("lab-d-05"));                           // leave one out
  await userEvent.click(screen.getByRole("button", { name: "Plan the rebuild" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rb1"));
  expect(posted(fn, "/api/clusters/c1/rebuild-nodes")).toEqual([{ nodes: ["lab-d-04"] }]);
});

test("a chosen host is sent with the rebuild", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/rebuild-nodes": [202, { operation_id: "rb2", change: {} }] });
  await panel();
  await waitFor(() => expect(screen.getByRole("option", { name: "pve2" })).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByLabelText("Proxmox host for a rebuild"), "pve2");
  await userEvent.click(screen.getByRole("button", { name: "Plan the rebuild" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rb2"));
  expect(posted(fn, "/api/clusters/c1/rebuild-nodes")).toEqual([{ nodes: ["lab-d-04", "lab-d-05"], pve_node: "pve2" }]);
});

test("forgetting needs the cluster name typed and posts it with the nodes", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/forget-nodes": [202, { operation_id: "fg1", change: {} }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Forget these nodes" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/nothing is destroyed, because the machines are already gone/)).toBeInTheDocument();
  const confirm = within(dialog).getByRole("button", { name: "Plan forgetting them" });
  expect(confirm).toBeDisabled();
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(confirm);
  await waitFor(() => expect(window.location.hash).toBe("#/operations/fg1"));
  expect(posted(fn, "/api/clusters/c1/forget-nodes")).toEqual([{ nodes: ["lab-d-04", "lab-d-05"], confirm_name: "lab-d" }]);
});

test("a refusal such as a red cluster is shown with its reason and nothing navigates", async () => {
  app(LIFE, { "POST /api/clusters/c1/rebuild-nodes": [409, { detail: "the cluster is red: 1 primary shard is not assigned (logs[0]), so data may already be lost." }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Plan the rebuild" }));
  expect(await screen.findByText(/the cluster is red: 1 primary shard is not assigned/)).toBeInTheDocument();
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("a node with a machine that Elasticsearch does not report is not offered a rebuild, and says why", async () => {
  app({ ...LIFE, node_state: { ...NODE_STATE, "lab-d-03": { machine: true, in_cluster: false } } });
  await panel();
  expect(screen.getByText(/lab-d-03 has a machine in Proxmox but is not in the cluster. That needs starting or restarting, which ECM does not do yet/)).toBeInTheDocument();
  expect(screen.queryByLabelText("lab-d-03")).not.toBeInTheDocument();
});

test("while another operation runs the form is replaced by a link to it", async () => {
  app({ ...LIFE, busy_operation_id: "op9" });
  await panel();
  const mine = screen.getByRole("heading", { name: "Recovery" }).closest(".ecm-lifecycle") as HTMLElement;
  expect(within(mine).getByRole("link", { name: "Open it" })).toHaveAttribute("href", "#/operations/op9");
  expect(screen.queryByRole("button", { name: "Plan the rebuild" })).not.toBeInTheDocument();
});
