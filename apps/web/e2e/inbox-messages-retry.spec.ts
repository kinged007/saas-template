import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

const CONVERSATION = {
  id: "conv-1",
  workspace_id: "ws-1",
  title: "Release plan",
  created_by_user_id: "user-1",
  last_message_at: "2026-01-02T10:00:00Z",
  last_message_preview: "shipping Friday",
  unread_count: 0,
  is_archived: false,
  participants: [],
  created_at: "2026-01-01T09:00:00Z",
  updated_at: "2026-01-02T10:00:00Z",
};

const MESSAGES = "**/api/v1/conversations/conv-1/messages**";

const MESSAGE_ROWS = [
  {
    id: "msg-1",
    conversation_id: "conv-1",
    sender_type: "user",
    sender_id: "user-1",
    sender_name: "E2E User",
    body: "shipping friday",
    created_at: "2026-01-02T10:00:00Z",
  },
];

/**
 * The message pane has no tripwire of its own — `queryClient.test.ts` pins that
 * the override exists, not that it still suppresses the storm. These are the
 * two shapes the pane has to survive: a transport failure (`statusCode: 0`,
 * which the client default retries 3 times) and a refusal (which it does not).
 * Either way the pane must say it failed; "No messages yet." is a claim about
 * the server's state that neither outcome supports.
 */
test.describe("inbox message fetch", () => {
  test("a network failure makes one attempt and renders the failure", async ({ page }) => {
    await mockApi(page, { signedIn: true, lists: { conversations: [CONVERSATION] } });

    let attempts = 0;
    await page.route(MESSAGES, async (route) => {
      attempts += 1;
      await route.abort("failed");
    });

    await page.goto("/inbox");
    await page.getByRole("button", { name: /Release plan/ }).click();

    await expect(page.getByText("Could not load messages.")).toBeVisible();
    await expect(page.getByText("No messages yet.")).toHaveCount(0);
    // Long enough to see the client's own budget (1s + 2s) fire if it ever does.
    await page.waitForTimeout(5_000);
    expect(attempts).toBe(1);
  });

  test("a 403 renders the failure instead of an empty conversation", async ({ page }) => {
    await mockApi(page, { signedIn: true, lists: { conversations: [CONVERSATION] } });

    let attempts = 0;
    await page.route(MESSAGES, async (route) => {
      attempts += 1;
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "You do not have permission to perform this action." }),
      });
    });

    await page.goto("/inbox");
    await page.getByRole("button", { name: /Release plan/ }).click();

    await expect(page.getByText("Could not load messages.")).toBeVisible();
    await expect(page.getByText("No messages yet.")).toHaveCount(0);
    await page.waitForTimeout(5_000);
    expect(attempts).toBe(1);
  });

  /**
   * A refetch that fails keeps the last successful `data` in the cache, so the
   * pane stays usable — but it has to say the list is not live. `refetchOnReconnect`
   * is the trigger: offline mode is what react-query's onlineManager reports.
   */
  test("a failed refetch keeps the messages and marks them stale", async ({ page, context }) => {
    await mockApi(page, { signedIn: true, lists: { conversations: [CONVERSATION] } });

    let refetchesFail = false;
    await page.route(MESSAGES, async (route) => {
      if (refetchesFail) return route.abort("failed");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MESSAGE_ROWS),
      });
    });

    await page.goto("/inbox");
    await page.getByRole("button", { name: /Release plan/ }).click();
    // `.first()` — the markdown body renders more than one node with the same text.
    await expect(page.getByText("shipping friday").first()).toBeVisible();

    refetchesFail = true;
    await context.setOffline(true);
    await context.setOffline(false);

    await expect(page.getByText("Showing the last messages loaded.")).toBeVisible();
    await expect(page.getByText("shipping friday").first()).toBeVisible();
    // `text-destructive` stays reserved for the empty list, where nothing loaded.
    await expect(page.getByText("Could not load messages.")).toHaveCount(0);
  });
});