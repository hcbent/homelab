import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const DISKS = { "lab-d-04": 100, "lab-d-05": 100, "lab-d-06": 150 };
const detail = (lifecycle: unknown) => ({
  id: "c1", name: "lab-d", uuid: null, version: "9.5.6", health: "green", ownership: "managed", nodes: 0, data_nodes: 0,
  infrastructure: { proxmox_hosts: [], verified_links: 0, total_nodes: 0 },
  storage: { total_bytes: 0, used_bytes: 0, used_pct: null }, jvm_heap_used_pct: null, jvm_heap_max_pct: null,
  last_sync_at: null, last_sync_error: null,
  elasticsearch: { health: {}, shards: { by_state: {}, by_node: {}, unassigned: [] }, settings: { persistent: {}, transient: {} } },
  desired: { managed: true, note: null }, node_list: [], lifecycle,
});
const LIFE = { managed: true, busy_operation_id: null, teardown_of: "create1", nodes: [], bootstrapped: true,
  can_remove: false, data_disks: DISKS, can_change: true };

function app(lifecycle: unknown, extra: Record<string, [number, unknown]> = {}) {
  const routes = table({ "GET /api/clusters/c1": [200, detail(lifecycle)], ...extra });
  const handler: Handler = (url, init) =>
    url.endsWith("/me") ? [200, { username: "admin", role: "admin" }] : routes(url, init);
  const fn = mockFetch(handler);
  render(<App />);
  return fn;
}
const panel = () => screen.findByRole("heading", { name: "Grow data disks" });
const sizeField = () => screen.getByLabelText("New size of each chosen disk (GB)");
const planButton = () => screen.getByRole("button", { name: "Plan the growth" });

test("the panel shows the current sizes, and the size must be larger than the biggest chosen disk", async () => {
  app(LIFE);
  await panel();
  expect(screen.getByText(/A disk can only be grown, never shrunk/)).toBeInTheDocument();
  expect(planButton()).toBeDisabled();
  await userEvent.type(sizeField(), "150");
  await userEvent.tab();
  expect(await screen.findByText(/Must be larger than 150 GB, the biggest of the chosen disks/)).toBeInTheDocument();
  expect(planButton()).toBeDisabled();
  await userEvent.clear(sizeField());
  await userEvent.type(sizeField(), "151");
  expect(planButton()).toBeEnabled();
  await userEvent.clear(sizeField());
  await userEvent.type(sizeField(), "70000");
  await userEvent.tab();
  expect(await screen.findByText("At most 65536 GB.")).toBeInTheDocument();
});

test("choosing fewer nodes lowers the bar to the biggest of those, and only they are sent", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/expand-disk": [202, { operation_id: "up1", change: {} }] });
  await panel();
  await userEvent.click(screen.getByLabelText("lab-d-06 (150 GB)"));           // leave the biggest out
  await userEvent.type(sizeField(), "120");
  expect(planButton()).toBeEnabled();
  await userEvent.click(planButton());
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/plan growing 2 data disks to 120 GB/)).toBeInTheDocument();
  expect(within(dialog).getByText(/This step changes nothing/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the growth" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/up1"));
  expect(posted(fn, "/api/clusters/c1/expand-disk")).toEqual([{ data_disk_gb: 120, nodes: ["lab-d-04", "lab-d-05"] }]);
});

test("with every node chosen, no node list is sent", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/expand-disk": [202, { operation_id: "up2", change: {} }] });
  await panel();
  await userEvent.type(sizeField(), "200");
  await userEvent.click(planButton());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the growth" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/up2"));
  expect(posted(fn, "/api/clusters/c1/expand-disk")).toEqual([{ data_disk_gb: 200 }]);
});

test("a refusal from the API is shown and the page stays", async () => {
  app(LIFE, { "POST /api/clusters/c1/expand-disk": [409, { detail: "pve2 has 50 GiB free on tank and this needs 100 GiB there" }] });
  await panel();
  await userEvent.type(sizeField(), "300");
  await userEvent.click(planButton());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the growth" }));
  expect(await screen.findByText(/pve2 has 50 GiB free on tank/)).toBeInTheDocument();
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("while an operation runs the form is replaced by a link to it", async () => {
  app({ ...LIFE, busy_operation_id: "op9", can_change: false });
  await panel();
  const links = screen.getAllByRole("link", { name: "Open it" });                 // this panel's and the teardown panel's
  expect(links.length).toBeGreaterThanOrEqual(1);
  links.forEach((link) => expect(link).toHaveAttribute("href", "#/operations/op9"));
  expect(screen.queryByLabelText("New size of each chosen disk (GB)")).not.toBeInTheDocument();
});

test("a cluster with no data disks, or one ECM did not build, has no growing panel", async () => {
  app({ ...LIFE, data_disks: {} });
  expect(await screen.findByText("Inside this cluster.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Grow data disks" })).not.toBeInTheDocument();
});
