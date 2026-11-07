import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const NODES = ["lab-d-01", "lab-d-02", "lab-d-03"];
const detail = (lifecycle: unknown, ownership = "managed") => ({
  id: "c1", name: "lab-d", uuid: null, version: "9.5.6", health: "green", ownership, nodes: 0, data_nodes: 0,
  infrastructure: { proxmox_hosts: [], verified_links: 0, total_nodes: 0 },
  storage: { total_bytes: 0, used_bytes: 0, used_pct: null }, jvm_heap_used_pct: null, jvm_heap_max_pct: null,
  last_sync_at: null, last_sync_error: null,
  elasticsearch: { health: {}, shards: { by_state: {}, by_node: {}, unassigned: [] }, settings: { persistent: {}, transient: {} } },
  desired: { managed: true, note: null }, node_list: [], lifecycle,
});
const BUILT = { managed: true, busy_operation_id: null, teardown_of: "create1", nodes: NODES, bootstrapped: true, can_remove: false };

/** The app with a signed-in user, the cluster page's own calls and whatever else a test adds. */
function app(lifecycle: unknown, extra: Record<string, [number, unknown]> = {}, ownership = "managed") {
  const routes = table({ "GET /api/clusters/c1": [200, detail(lifecycle, ownership)], ...extra });
  const handler: Handler = (url, init) =>
    url.endsWith("/me") ? [200, { username: "admin", role: "admin" }] : routes(url, init);
  const fn = mockFetch(handler);
  render(<App />);
  return fn;
}
const panel = () => screen.findByRole("heading", { name: "Tear down or remove" });

test("a built cluster names the machines and the data loss, and the teardown waits for the typed name", async () => {
  const fn = app(BUILT, { "POST /api/operations/create1/cleanup": [202, { id: "destroy1" }] });
  await panel();
  expect(screen.getByText("lab-d-01, lab-d-02, lab-d-03")).toBeInTheDocument();
  expect(screen.getByText("Elasticsearch is running on these machines")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove record" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Tear down cluster" }));
  const dialog = await screen.findByRole("alertdialog");
  const confirm = within(dialog).getByRole("button", { name: "Plan the teardown" });
  expect(confirm).toBeDisabled();
  expect(within(dialog).getByText(/changes nothing yet/)).toBeInTheDocument();
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  expect(confirm).toBeEnabled();
  await userEvent.click(confirm);

  await waitFor(() => expect(window.location.hash).toBe("#/operations/destroy1"));
  expect(posted(fn, "/api/operations/create1/cleanup")).toEqual([{ confirm_name: "lab-d", confirm_data_loss: true }]);
});

test("a cluster that never bootstrapped is torn down without a data loss warning or acceptance", async () => {
  const fn = app({ ...BUILT, bootstrapped: false },
    { "POST /api/operations/create1/cleanup": [202, { id: "destroy2" }] });
  await panel();
  expect(screen.queryByText("Elasticsearch is running on these machines")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Tear down cluster" }));
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the teardown" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/destroy2"));
  expect(posted(fn, "/api/operations/create1/cleanup")).toEqual([{ confirm_name: "lab-d", confirm_data_loss: false }]);
});

test("a refusal from the API is shown and the page stays put", async () => {
  app(BUILT, { "POST /api/operations/create1/cleanup": [409, { detail: "this create has already been cleaned up" }] });
  await panel();
  await userEvent.click(screen.getByRole("button", { name: "Tear down cluster" }));
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the teardown" }));
  expect(await screen.findByText("this create has already been cleaned up")).toBeInTheDocument();
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("while an operation runs, nothing is offered and the operation is linked", async () => {
  app({ ...BUILT, busy_operation_id: "op9", teardown_of: null, nodes: [] });
  await panel();
  expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute("href", "#/operations/op9");
  expect(screen.queryByRole("button", { name: "Tear down cluster" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove record" })).not.toBeInTheDocument();
});

test("once the machines are gone only the removal is offered, and it needs the typed name", async () => {
  const fn = app({ managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: false, can_remove: true },
    { "POST /api/clusters/c1/remove": [200, { id: "c1", name: "lab-d", operations_kept: 3 }] });
  await panel();
  expect(screen.queryByRole("button", { name: "Tear down cluster" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove record" }));
  const dialog = await screen.findByRole("alertdialog");
  const confirm = within(dialog).getByRole("button", { name: "Remove" });
  expect(confirm).toBeDisabled();
  await userEvent.type(within(dialog).getByLabelText("Type lab-d to confirm"), "lab-d");
  await userEvent.click(confirm);
  await waitFor(() => expect(window.location.hash).toBe("#/"));
  expect(posted(fn, "/api/clusters/c1/remove")).toEqual([{ confirm_name: "lab-d" }]);
});

test("a cluster ECM did not build has no teardown panel", async () => {
  app({ managed: false }, {}, "discovered");
  expect(await screen.findByText("Inside this cluster.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Tear down or remove" })).not.toBeInTheDocument();
});

test("the Operations tab lists this cluster's operations only, each linked", async () => {
  const op = (id: string, kind: string, state: string, cluster_id: string | null, dry_run = false) =>
    ({ id, kind, state, phase: null, elapsed_seconds: 1, error: null, cluster_id, dry_run, started_at: null });
  app(BUILT, { "GET /api/operations": [200, [
    op("a1", "tf.destroy", "pending_approval", "c1"), op("a2", "tf.create", "succeeded", "c1"),
    op("a3", "tf.create", "succeeded", "other"), op("a4", "tf.create", "succeeded", "c1", true)] ] });
  await panel();
  await userEvent.click(screen.getByRole("tab", { name: "Operations" }));
  const table = await screen.findByRole("table");   // the only table once the Nodes tab is left
  expect(within(table).getByRole("link", { name: "Tear down cluster" })).toHaveAttribute("href", "#/operations/a1");
  expect(within(table).getAllByRole("link", { name: "Create cluster" })).toHaveLength(2);   // a2 and the dry run a4
  expect(within(table).getByText("dry run")).toBeInTheDocument();
  expect(within(table).getByText("waiting for approval")).toBeInTheDocument();
});

test("when nothing can be offered, the panel says why instead of claiming there is nothing to do", async () => {
  app({ managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: false, can_remove: false,
    remove_blocker: "VMs named lab-d-01 still exist in Proxmox; remove them first" });
  await panel();
  expect(screen.getByText(/cannot be removed yet: VMs named lab-d-01 still exist in Proxmox/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove record" })).not.toBeInTheDocument();
});
