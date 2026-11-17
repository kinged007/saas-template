import assert from "node:assert/strict";
import { test } from "node:test";

import { countAuthInvalidations, stripComments, useUpdateProfileWindow } from "./query-keys-guard.ts";

const AUTH_HIT = 'invalidateQueries({ queryKey: ["auth"] })';

// useUpdateProfile with one real ["auth"] invalidation, followed by `after`.
const sourceWithFollowing = (after: string) =>
  [
    "export function useUpdateProfile() {",
    "  const update = useCallback(() => {",
    `    queryClient.${AUTH_HIT};`,
    "  });",
    "  return update;",
    "}",
    "",
    after,
  ].join("\n");

test("the window closes at a hook exported as export const, not at the next export function", () => {
  const source = sourceWithFollowing(
    [
      "export const useWidener = () => {",
      `  queryClient.${AUTH_HIT};`,
      "};",
      "",
      "export function useThird() {",
      "  return 1;",
      "}",
    ].join("\n"),
  );
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 1);
});

test("the window closes at a following export async function", () => {
  const source = sourceWithFollowing(
    [
      "export async function useWidener() {",
      `  await queryClient.${AUTH_HIT};`,
      "}",
      "",
      "export function useThird() {",
      "  return 1;",
      "}",
    ].join("\n"),
  );
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 1);
});

test("the window extends to EOF when useUpdateProfile is the last export", () => {
  const source = sourceWithFollowing("const notExported = 1;");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.ok(region.includes("notExported"));
  assert.equal(countAuthInvalidations(region), 1);
});

test("a comment naming the invalidation is not counted", () => {
  const source = [
    "export function useUpdateProfile() {",
    `  /* ${AUTH_HIT} */`,
    `  // ${AUTH_HIT};`,
    "  return 1;",
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 0);
});

test("a real invalidation beside comments is still counted once", () => {
  const source = [
    "export function useUpdateProfile() {",
    `  // ${AUTH_HIT}`,
    `  queryClient.${AUTH_HIT};`,
    "  return 1;",
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 1);
});

test("the window is missing when the hook is not a plain export function", () => {
  assert.equal(useUpdateProfileWindow("export const useUpdateProfile = makeHook();"), null);
});

test("a preceding hook whose name extends the needle cannot anchor the window", () => {
  const source = [
    "export function useUpdateProfileAvatar() {",
    `  queryClient.${AUTH_HIT};`,
    `  queryClient.${AUTH_HIT};`,
    "}",
    "",
    "export function useUpdateProfile() {",
    `  queryClient.${AUTH_HIT};`,
    "}",
    "",
    "export function useFollower() {",
    `  queryClient.${AUTH_HIT};`,
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.ok(region.startsWith("export function useUpdateProfile("), "window starts at the hook itself");
  assert.equal(countAuthInvalidations(region), 1);
});

test("an invalidation carrying extra options is still counted", () => {
  const source = [
    "export function useUpdateProfile() {",
    `  queryClient.${AUTH_HIT};`,
    '  queryClient.invalidateQueries({ queryKey: ["auth"], refetchType: "none" });',
    "  queryClient.invalidateQueries({",
    '    queryKey: ["auth"],',
    '    refetchType: "none",',
    "  });",
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 3);
});

test("a longer key sharing the [\"auth\"] prefix is still not counted", () => {
  const source = [
    "export function useUpdateProfile() {",
    '  queryClient.invalidateQueries({ queryKey: ["auth", "identity"] });',
    '  queryClient.invalidateQueries({ queryKey: ["auth"], refetchType: "none" });',
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 1);
});

test("a commented-out export at line start inside the hook cannot truncate the window", () => {
  const source = [
    "export function useUpdateProfile() {",
    "/*",
    "export const useGhost = () => {",
    `  queryClient.${AUTH_HIT};`,
    "};",
    "*/",
    `  queryClient.${AUTH_HIT};`,
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 1);
  assert.ok(!region.includes("useGhost"), "the ghost comment is not part of the window");
});

test("a commented-out export between the hook and the next hook cannot widen the window", () => {
  const source = [
    "export function useUpdateProfile() {",
    `  queryClient.${AUTH_HIT};`,
    "}",
    "/*",
    "export const useGhost = () => {",
    `  queryClient.${AUTH_HIT};`,
    "};",
    "*/",
    "export function useFollower() {",
    `  queryClient.${AUTH_HIT};`,
    "}",
  ].join("\n");
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null);
  assert.equal(countAuthInvalidations(region), 1);
  assert.ok(!region.includes("useGhost"), "the ghost comment is not part of the window");
});

test("stripComments keeps https:// while dropping comments", () => {
  assert.equal(stripComments('/* a */ const u = "https://x"; // b'), ' const u = "https://x"; ');
});
