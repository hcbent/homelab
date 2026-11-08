import { DEFAULT_ROLES, rolesFromText, rolesText } from "./roles";

test("a node with Elasticsearch's default roles reads as all roles, in any order", () => {
  expect(rolesText(DEFAULT_ROLES)).toBe("all roles");
  expect(rolesText([...DEFAULT_ROLES].reverse())).toBe("all roles");
});

test("a node with no roles is coordinating only, and any other set is listed, sorted", () => {
  expect(rolesText([])).toBe("coordinating only");
  expect(rolesText(["ml", "remote_cluster_client"])).toBe("ml, remote_cluster_client");
  expect(rolesText(["master", "data"])).toBe("data, master");
});

test("a set that is almost the default is listed, so a missing or extra role is not hidden", () => {
  expect(rolesText(DEFAULT_ROLES.filter((r) => r !== "transform"))).toContain("remote_cluster_client");
  expect(rolesText([...DEFAULT_ROLES, "voting_only"])).toContain("voting_only");
});

test("the text a plan carries is shortened the same way, and anything else is left as it is", () => {
  expect(rolesFromText(DEFAULT_ROLES.join(", "))).toBe("all roles");
  expect(rolesFromText("none (coordinating only)")).toBe("coordinating only");
  expect(rolesFromText("ml")).toBe("ml");
  expect(rolesFromText("the default roles")).toBe("the default roles");
});
