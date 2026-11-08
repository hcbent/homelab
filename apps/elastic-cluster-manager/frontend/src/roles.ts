/** Elasticsearch's default roles: every role except voting_only (the same set the backend calls DEFAULT_ROLES). A node with all of them is
 * shown as "all roles" instead of a line of eleven names. */
export const DEFAULT_ROLES = ["data", "data_cold", "data_content", "data_frozen", "data_hot", "data_warm", "ingest", "master", "ml",
  "remote_cluster_client", "transform"];

/** A node's roles in a short form: nothing for a coordinating-only node, "all roles" for the default set, otherwise the names. */
export function rolesText(roles: string[]): string {
  if (roles.length === 0) return "coordinating only";
  const have = new Set(roles);
  if (have.size === DEFAULT_ROLES.length && DEFAULT_ROLES.every((r) => have.has(r))) return "all roles";
  return [...roles].sort().join(", ");
}

/** The same for the text the API puts in a plan ("ml", "data, ingest", "none (coordinating only)", or a long list). */
export function rolesFromText(text: string): string {
  if (!text || text.startsWith("none")) return "coordinating only";
  const names = text.split(",").map((r) => r.trim()).filter(Boolean);
  const known = names.every((r) => /^[a-z_]+$/.test(r));
  return known ? rolesText(names) : text;
}
