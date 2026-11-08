# To do

Small known problems and follow-ups that are not part of a phase. Add an item when one is found; remove it when it is fixed (the
fix goes in `DECISIONS.md` if it taught anything).

## The roles multi-select on *Add nodes* renders badly

**Found 2026-11-07 on infra, from the operator's screenshot of the *Add nodes* panel with "Choose the roles" selected.** The selected
roles (`ml` and `remote_cluster_client`) are drawn as pills whose outline is too small for the text: the `ml` pill's outline is
empty, with its label and × sitting below it, and the `remote_cluster_client` pill's label overflows the bottom of its outline.
The clear-all (×) button on the right of the field also looks off, a tall circle that overlaps the field's edge. The field still
works (the roles were chosen and the form accepted them); only the drawing is wrong.

What to look at first, none of it confirmed:

- EUI sizes each pill by measuring its text, and the self-hosted Inter font may load after that measurement, so the pills are sized for a
  different font. (The tests stub the measurement, so they cannot show this.)
- A rule in `src/index.css` (a line height, a font size or a `.euiBadge` / `.euiComboBoxPill` override) may be shrinking the pill's
  box without shrinking its text.
- The same field in light mode and at other widths, to see whether it is the theme or the layout.

Done when the pills and the clear button draw correctly in dark and light mode with one, two and several roles chosen (check at least
`ml` and `remote_cluster_client`, the two longest-looking cases), with a note in `DECISIONS.md` on the cause.

## Spacing on the plan page around "Where each new node goes"

**Found 2026-11-07 on infra, from the operator's screenshot of an add-nodes operation.** On the plan panel, the "WHERE EACH NEW NODE
GOES" heading sits directly under the "Plan digest" row with no gap, while the rest of the panel is spaced (the title, then the three
rows, then the table with room around it). The spacing between the parts of the plan panel is not consistent.

Probably the table block (`AddedNodes` in `src/OperationDetail.tsx`, in a `.ecm-stack-lg` wrapper) is placed straight after the
description list with no margin of its own, so its gap applies inside it and not above it. Not confirmed, and the dry-run note and the
Approve buttons below it should be looked at in the same pass, since they were spaced by hand elsewhere (`ecm-gap`, `ecm-detail__actions`).

Done when the heading has the same space above it as the other blocks in the panel, in dark and light mode, for an add-nodes plan with
and without placement warnings and with and without the dry-run note.

## A default-roles node lists all eleven roles

**Found 2026-11-07 on infra, from the operator's screenshots of the Remove nodes panel and the node table.** A node with Elasticsearch's default
roles is shown as `data, data_cold, data_content, data_frozen, data_hot, data_warm, ingest, master, ml, remote_cluster_client, transform` in the
Remove nodes panel's labels and in the cluster page's node table, which wraps to three lines. For a default-roles node the recorded state says
so (`roles_mode: default`), and the live node reports the same list, so "all roles" (or "default roles") could be shown instead, with the full
list in a tooltip. The same list shows on the plan page's table for removed and added nodes.

Done when a default-roles node reads as one short phrase in the Remove nodes panel, the node table and the plan tables, and a node with a custom set
of roles still lists them.

## The Recovery panel can be up to five minutes stale, and says so as if it were fact

**Found 2026-11-08 on infra, from the operator's first live test of a rebuild.** The operator deleted a node's VM in Proxmox and pressed *Sync now* on the cluster page. That
button refreshes only Elasticsearch (`POST /api/clusters/{id}/sync`), so the cluster went yellow with the node missing while ECM's Proxmox inventory still held the VM's row (the
Proxmox connection syncs separately: every 5 minutes, or from the Infrastructure page). The Recovery panel then read "test-5a-05 has a machine in Proxmox but is not in the cluster.
That needs starting or restarting" and offered no rebuild, which is the right answer for the data it had and the wrong one for what was true.

Two changes, neither made yet:

- *Sync now* on a managed cluster also syncs the cluster's Proxmox connection (`desired.proxmox_connection_id`), a read-only call, and reports an error from either.
- The panel says when the Proxmox data it relies on was taken ("as of the last Proxmox sync, 4 minutes ago") instead of stating that a machine exists.

Done when deleting a VM and pressing *Sync now* once on the cluster page is enough to make the Recovery panel offer the rebuild, and the panel's text shows how old the Proxmox reading is.

## A "Copy log" button on the log window

**Asked for 2026-11-08, after the operator had trouble copying a rebuild's log out of the operation page.** The log window (`OperationDetail.tsx`, the `<pre aria-label="Operation log">`, the only
one in the app) shows the last 400 lines (`MAX_LOG_LINES`) and says "217 earlier lines are not shown", and selecting text in a scrolling box is awkward. The API already returns every line of an
operation's log (`GET /api/operations/{id}` has no limit), so the page holds the whole log in memory, not just the 400 it draws.

Add a **Copy log** button beside the log heading that copies the **whole** log (every line of `op.logs`, not only the 400 shown) to the clipboard, in the same `[stream] line` form the window uses, and
says it did ("Copied 617 lines"). Use `navigator.clipboard.writeText`, with a fallback for a context where it is not available, and say so if the copy fails. If the log is large, copying should not freeze
the page.

Done when pressing it on an operation with more than 400 lines puts every line on the clipboard, a test shows the clipboard text holds the hidden lines too and the confirmation names the count, and a
failed copy says it failed. A **Download log** button next to it would be a natural small addition (a text file named for the operation), but is not asked for.

## Two warnings say the same thing on a rebuild's plan page

**Found 2026-11-08, from the operator's screenshot of a master rebuild on a host that already had one.** The plan page lists "master-eligible nodes test-5a-01, test-5a-03 are pinned to the same Proxmox host (pve2);
losing it would break the master quorum" (from the desired-state warnings) and then "host 'pve2' would hold 2 of 3 master-eligible nodes ... This is allowed because the cluster is being recovered ..." (from the
placement). The second is clearer, and the first adds nothing. On a rebuild, drop the desired-state warning when the placement warning covers the same host, and keep the "goes to X, not Y where it was" line.

Done when a rebuild that puts a master on a host that already has one shows the placement warning once, and a rebuild with no such problem shows no master warning at all.

