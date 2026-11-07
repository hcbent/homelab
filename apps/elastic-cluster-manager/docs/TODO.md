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
