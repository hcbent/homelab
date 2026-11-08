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
  "lab-d-03": { roles: ["master"], master_eligible: true, holds_data: false, host: "pve3" },
  "lab-d-04": { roles: ["data", "ingest"], master_eligible: false, holds_data: true, host: "pve1" },
  "lab-d-05": { roles: [], master_eligible: false, holds_data: false, host: "pve2" },
};
const LIFE = { managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: true,
  can_remove: false, data_disks: {}, can_change: true, sizes: {}, node_roles: NODE_ROLES };
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
const panel = () => screen.findByRole("heading", { name: "Remove nodes" });
const plan = () => screen.getByRole("button", { name: "Plan the removal" });
/** The panel's own contents: the Restart panel lists the same nodes, so a page-wide label query would find both. */
const inPanel = async () => within((await panel()).closest(".ecm-lifecycle") as HTMLElement);

test("the panel says the data moves first, shows each node with its roles and host, and counts the masters", async () => {
  app(LIFE);
  const mine = await inPanel();
  expect(screen.getByText("The data is moved off a node before its machine is destroyed")).toBeInTheDocument();
  expect(screen.getByText(/The cluster has 3 master-eligible nodes: it needs at least 3/)).toBeInTheDocument();
  expect(mine.getByLabelText("lab-d-01: master (counts towards the master quorum), on pve1")).toBeInTheDocument();
  expect(mine.getByLabelText("lab-d-04: data, ingest, on pve1")).toBeInTheDocument();
  expect(mine.getByLabelText("lab-d-05: coordinating only, on pve2")).toBeInTheDocument();
  expect(plan()).toBeDisabled();                                                       // nothing is chosen yet
});

test("nothing is sent until the cluster name is typed, and then the chosen nodes and the name are posted", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/remove-nodes": [202, { operation_id: "rm1", change: {} }] });
  const mine = await inPanel();
  await userEvent.click(mine.getByLabelText(/lab-d-05/));
  await userEvent.click(mine.getByLabelText(/lab-d-04/));
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/ECM will check whether lab-d-04, lab-d-05 can be removed/)).toBeInTheDocument();
  expect(within(dialog).getByText(/destroys their machines and disks for good/)).toBeInTheDocument();
  const confirm = within(dialog).getByRole("button", { name: "Plan the removal" });
  expect(confirm).toBeDisabled();
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(confirm);
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rm1"));
  expect(posted(fn, "/api/clusters/c1/remove-nodes")).toEqual([{ nodes: ["lab-d-04", "lab-d-05"], confirm_name: "lab-d" }]);
});

test("a refusal from ECM is shown with its reason and nothing navigates", async () => {
  app(LIFE, { "POST /api/clusters/c1/remove-nodes": [409, { detail: "removing lab-d-01 would break the quorum: only 2 master-eligible nodes would remain" }] });
  const mine = await inPanel();
  await userEvent.click(mine.getByLabelText(/lab-d-01/));
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the removal" }));
  const alert = await screen.findByText(/only 2 master-eligible nodes would remain/);
  expect(alert).toBeInTheDocument();
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("while another operation runs the form is replaced by a link to it", async () => {
  app({ ...LIFE, busy_operation_id: "op9" });
  await panel();
  const mine = screen.getByRole("heading", { name: "Remove nodes" }).closest(".ecm-lifecycle") as HTMLElement;
  expect(within(mine).getByRole("link", { name: "Open it" })).toHaveAttribute("href", "#/operations/op9");
  expect(screen.queryByRole("button", { name: "Plan the removal" })).not.toBeInTheDocument();
});

test("a cluster that cannot be changed, or is not one ECM built, offers nothing to remove", async () => {
  app({ ...LIFE, can_change: false });
  const mine = (await panel()).closest(".ecm-lifecycle") as HTMLElement;
  expect(within(mine).getByText("This cluster cannot be changed right now.")).toBeInTheDocument();
  expect(within(mine).queryByLabelText(/lab-d-01/)).not.toBeInTheDocument();
});
