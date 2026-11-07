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
