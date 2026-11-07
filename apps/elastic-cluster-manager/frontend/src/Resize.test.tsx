import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { Handler, mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/clusters/c1"; });

const SIZES = {
  "lab-d-01": { cores: 2, ram_mb: 4096 }, "lab-d-02": { cores: 2, ram_mb: 4096 }, "lab-d-03": { cores: 4, ram_mb: 8192 },
};
const LIFE = { managed: true, busy_operation_id: null, teardown_of: null, nodes: [], bootstrapped: true,
  can_remove: false, data_disks: {}, can_change: true, sizes: SIZES };
const detail = (lifecycle: unknown) => ({
  id: "c1", name: "lab-d", uuid: null, version: "9.5.6", health: "green", ownership: "managed", nodes: 0, data_nodes: 0,
  infrastructure: { proxmox_hosts: [], verified_links: 0, total_nodes: 0 },
  storage: { total_bytes: 0, used_bytes: 0, used_pct: null }, jvm_heap_used_pct: null, jvm_heap_max_pct: null,
  last_sync_at: null, last_sync_error: null,
  elasticsearch: { health: {}, shards: { by_state: {}, by_node: {}, unassigned: [] }, settings: { persistent: {}, transient: {} } },
  desired: { managed: true, note: null }, node_list: [], lifecycle,
});

function app(lifecycle: unknown, extra: Record<string, [number, unknown]> = {}) {
  const routes = table({ "GET /api/clusters/c1": [200, detail(lifecycle)], ...extra });
  const handler: Handler = (url, init) =>
    url.endsWith("/me") ? [200, { username: "admin", role: "admin" }] : routes(url, init);
  const fn = mockFetch(handler);
  render(<App />);
  return fn;
}
const panel = () => screen.findByRole("heading", { name: /Resize nodes/ });
const cores = () => screen.getByLabelText("Cores per node (leave empty to keep)");
const ram = () => screen.getByLabelText("RAM per node, GiB (leave empty to keep)");
const plan = () => screen.getByRole("button", { name: "Plan the resize" });

test("the panel is marked a preview, says the machines are not restarted, and shows the current sizes", async () => {
  app(LIFE);
  await panel();
  expect(screen.getByText("preview")).toBeInTheDocument();
  expect(screen.getByText("ECM does not restart the machines yet")).toBeInTheDocument();
  expect(screen.getAllByText(/2 cores, 4 GiB/).length).toBeGreaterThanOrEqual(2);       // two nodes have that size
  expect(plan()).toBeDisabled();
});

test("something must be entered and it must be sensible", async () => {
  app(LIFE);
  await panel();
  await userEvent.type(cores(), "0");
  await userEvent.tab();
  expect(await screen.findByText("Cores must be a whole number from 1 to 64.")).toBeInTheDocument();
  expect(plan()).toBeDisabled();
  await userEvent.clear(cores());
  await userEvent.type(ram(), "1");
  expect(await screen.findByText("RAM must be a whole number of GiB from 2 to 512.")).toBeInTheDocument();
  await userEvent.clear(ram());
  await userEvent.type(ram(), "16");
  expect(plan()).toBeEnabled();
});

test("RAM is entered in GiB and sent in MB, with a node list only when fewer than all are chosen", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/resize": [202, { operation_id: "rs1", change: {} }] });
  await panel();
  await userEvent.click(screen.getByLabelText(/lab-d-03 \(4 cores, 8 GiB\)/));       // leave one out
  await userEvent.type(cores(), "8");
  await userEvent.type(ram(), "16");
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/they are\s+not restarted|not restarted/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the resize" }));
  await waitFor(() => expect(window.location.hash).toBe("#/operations/rs1"));
  expect(posted(fn, "/api/clusters/c1/resize")).toEqual([{ cores: 8, ram_mb: 16384, nodes: ["lab-d-01", "lab-d-02"] }]);
});

test("only the field that is filled in is sent, and a refusal is shown", async () => {
  const fn = app(LIFE, { "POST /api/clusters/c1/resize": [409, { detail: "pve2 has 3000 MiB of memory free and this needs 8192 MiB more there" }] });
  await panel();
  await userEvent.type(ram(), "12");
  await userEvent.click(plan());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Plan the resize" }));
  expect(await screen.findByText(/pve2 has 3000 MiB of memory free/)).toBeInTheDocument();
  expect(posted(fn, "/api/clusters/c1/resize")).toEqual([{ ram_mb: 12288 }]);
  expect(window.location.hash).toBe("#/clusters/c1");
});

test("a single-node cluster is not offered a resize, and a busy cluster shows a link instead of the form", async () => {
  app({ ...LIFE, sizes: { "solo-01": { cores: 2, ram_mb: 4096 } } });
  await panel();
  expect(screen.getByText(/single-node cluster would be down while its machine restarts/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Plan the resize" })).not.toBeInTheDocument();
});

test("a busy cluster shows a link to the running operation", async () => {
  app({ ...LIFE, busy_operation_id: "op9", can_change: false });
  await panel();
  expect(screen.queryByLabelText("Cores per node (leave empty to keep)")).not.toBeInTheDocument();
  screen.getAllByRole("link", { name: "Open it" }).forEach((l) => expect(l).toHaveAttribute("href", "#/operations/op9"));
});

test("a cluster with no recorded sizes has no resize panel", async () => {
  app({ ...LIFE, sizes: {} });
  expect(await screen.findByText("Inside this cluster.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /Resize nodes/ })).not.toBeInTheDocument();
});
