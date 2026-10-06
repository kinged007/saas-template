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

const OTHER_CONVERSATION = { ...CONVERSATION, id: "conv-2", title: "Design review", last_message_preview: "looks good" };

const MESSAGES = "**/api/v1/conversations/conv-1/messages**";

// Enough rows to overflow the message pane: the pane auto-scrolls to the newest
// message, so a caption rendered inside the scroller would sit off-screen.
const MESSAGE_ROWS = Array.from({ length: 25 }, (_, i) => ({
  id: `msg-${i + 1}`,
  conversation_id: "conv-1",
  sender_type: "user",
  sender_id: "user-1",
  sender_name: "E2E User",
  body: `shipping friday #${i + 1}`,
  created_at: "2026-01-02T10:00:00Z",
}));

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
   * pane stays usable — but it has to say the list is not live, and it has to say
   * it where the user is looking. The pane holds more messages than fit and is
   * scrolled to the newest, so the note is pinned to the top edge of the message
   * scroller as a non-layout overlay: it stays visible at any scroll position
   * without shifting the thread header, the rows, or the scroll position. The
   * containment assertions below are what keep it there.
   */
  test("a failed refetch keeps the messages and marks them stale", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      lists: { conversations: [CONVERSATION, OTHER_CONVERSATION] },
    });
    // Reopening a conversation remounts its observer, which refetches over the
    // cached rows. That is the refetch under test; `refetchOnReconnect` needs
    // `context.setOffline`, which does not reach the browser here — the window
    // events it emits schedule no refetch on this headless build.
    await page.route("**/api/v1/conversations/conv-2/messages**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    // "ok" | "forbid" (4xx) | "fail" (transport)
    let mode: "ok" | "forbid" | "fail" = "ok";
    await page.route(MESSAGES, async (route) => {
      if (mode === "fail") return route.abort("failed");
      if (mode === "forbid") {
        return route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "You do not have permission to perform this action." }),
        });
      }
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

    // A refusal is not stale data, so it must not read as "the last messages loaded".
    mode = "forbid";
    await page.getByRole("button", { name: /Design review/ }).click();
    await page.getByRole("button", { name: /Release plan/ }).click();
    await expect(page.getByText("Could not refresh messages.")).toBeVisible();
    await expect(page.getByText("Showing the last messages loaded.")).toHaveCount(0);

    mode = "fail";
    await page.getByRole("button", { name: "Retry" }).click();
    // The live region is always mounted and only its text toggles, so locate the
    // region itself rather than the text node.
    const staleNote = page.locator('[role="status"]', { hasText: "Showing the last messages loaded." });
    await expect(staleNote).toBeVisible();
    await expect(staleNote).toHaveAttribute("role", "status");
    // The guard for the placement: `toBeVisible` and `toBeInViewport` both pass when the
    // note is the first child of the header above the scroller. The note has to live in
    // the scroller itself, as its direct child — pinned to the scroller's top edge, above
    // the rows container, so it is a sibling of that container and never of the rows.
    const notePinnedToScroller = await staleNote.evaluate((note) => {
      const scroller = note.closest(".overflow-y-auto");
      return scroller !== null && note.parentElement === scroller;
    });
    expect(notePinnedToScroller).toBe(true);
    await expect(staleNote).toBeInViewport();
    await expect(page.getByText("shipping friday").first()).toBeVisible();
    // `text-destructive` stays reserved for the empty list, where nothing loaded.
    await expect(page.getByText("Could not load messages.")).toHaveCount(0);

    mode = "ok";
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(staleNote).toHaveCount(0);
  });
});
