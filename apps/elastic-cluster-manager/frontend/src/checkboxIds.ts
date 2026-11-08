/**
 * EUI uses a checkbox option's `id` as the DOM id of its input. Several panels on the cluster page list the same node names, so a bare
 * node name as the id made the ids repeat, and a label in a later panel then toggled the first panel's checkbox. Each panel prefixes
 * its own: `ids("remove").id("lab-d-01")` is `remove-lab-d-01`, and `.name(...)` undoes it.
 */
export function ids(panel: string) {
  return { id: (node: string) => `${panel}-${node}`, name: (id: string) => id.slice(panel.length + 1) };
}
