import assert from "node:assert/strict";
import { test } from "node:test";

import type { Notification } from "../types";
import { notificationLinkUrl } from "./notificationLink.ts";

const withUrl = (url: unknown): Notification =>
  ({ id: "n-1", payload: { url } }) as unknown as Notification;

test("keeps in-app paths as-is", () => {
  assert.equal(notificationLinkUrl(withUrl("/invitations")), "/invitations");
  assert.equal(
    notificationLinkUrl(withUrl("/inbox?tab=notifications#x")),
    "/inbox?tab=notifications#x",
  );
  assert.equal(notificationLinkUrl(withUrl("invitations")), "/invitations");
});

test("returns undefined when there is no usable link", () => {
  assert.equal(notificationLinkUrl({ id: "n-1" } as Notification), undefined);
  assert.equal(notificationLinkUrl(withUrl(undefined)), undefined);
  assert.equal(notificationLinkUrl(withUrl(42)), undefined);
  assert.equal(notificationLinkUrl(withUrl("")), undefined);
  assert.equal(notificationLinkUrl(withUrl("   ")), undefined);
});

test("normalises same-origin spellings to a root-relative path", () => {
  assert.equal(notificationLinkUrl(withUrl("//same-origin.invalid/x")), "/x");
  assert.equal(notificationLinkUrl(withUrl("?q=1")), "/?q=1");
  assert.equal(
    notificationLinkUrl(withUrl("https://same-origin.invalid/x")),
    "/x",
  );
});

test("accepted links are always root-relative paths", () => {
  for (const url of [
    "/invitations",
    "/inbox?tab=notifications#x",
    "invitations",
    "?q=1",
    "//same-origin.invalid/x",
    "https://same-origin.invalid/x",
  ]) {
    const link = notificationLinkUrl(withUrl(url));
    assert.ok(link !== undefined, url);
    assert.ok(link.startsWith("/"), `${url} -> ${link}`);
    assert.ok(!link.startsWith("//"), `${url} -> ${link}`);
  }
});

test("rejects off-origin and non-path values", () => {
  for (const url of [
    "//evil.com",
    "/\\evil.com",
    "/\\\\evil.com",
    "/\t/evil.com",
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "https://evil.com/x",
    "data:text/html,x",
    "mailto:a@b.c",
    "http://[",
  ]) {
    assert.equal(notificationLinkUrl(withUrl(url)), undefined, url);
  }
});
