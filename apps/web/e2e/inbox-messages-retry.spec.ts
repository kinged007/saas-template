import { expect, type Page } from "playwright/test";

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
 * A failed messages query must be flagged by the pane's own note — refine's
 * default error toast would echo it transiently. The toast mounts in a later
 * effect tick than the note's commit, so its absence only counts as a settled
 * absence: settle past the mount window first. Sonner keeps a mounted toast
 * up ~4s, so an absence measured after this wait holds for its lifetime.
 */
async function expectNoRefineToast(page: Page) {
  await page.waitForTimeout(2_000);
  // Refine's error notifications go through sonner's `toast.error`, which
  // renders the toast with `data-type="error"`, so scope the check to error
  // toasts instead of every sonner toast: a success toast on one of these
  // flows (say one for the Retry action) must not trip the failure paths.
  await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
}

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
    // The destructive empty-pane text is the failure signal; refine's default
    // toast is suppressed on this query too.
    await expectNoRefineToast(page);
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
    await expectNoRefineToast(page);
    await page.waitForTimeout(5_000);
    expect(attempts).toBe(1);
  });

  /**
   * A refetch that fails keeps the last successful `data` in the cache, so the
   * pane stays usable — but it has to say the list is not live, and it has to say
   * it where the user is looking. The pane holds more messages than fit and is
   * scrolled to the newest, so the note is sticky at the top edge of the message
   * scroller: it stays visible at any scroll position, and the scroller's scroll
   * anchoring keeps the reading position stable when it appears. The
   * containment and scrolled-state assertions below are what keep it there.
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
    // The inline note is the only failure signal on a warm cache: refine's
    // default toast stays suppressed on this query, so it cannot echo the note
    // transiently next to it.
    await expectNoRefineToast(page);
    // The guard for the placement: `toBeVisible` and `toBeInViewport` both pass when
    // the note is the first child of a pane that happens not to be scrolled. It is
    // measured against the message scroller — the one the note must not live in —
    // anchored on the scroller's own test id, so the assertion depends on the
    // note's DOM position alone and not on fixture text matching the note text. It is
    // a double lock: the data-testid anchor excludes the conversation list while
    // `parentElement === scroller` pins the note as the scroller's direct child,
    // keeping the sticky top row free of row-flow artifacts.
    const scrollerCheck = await staleNote.evaluate((note) => {
      const scroller = note.closest('[data-testid="thread-messages"].overflow-y-auto');
      return {
        found: scroller !== null,
        directChild: scroller !== null && note.parentElement === scroller,
      };
    });
    expect(scrollerCheck.found).toBe(true);
    expect(scrollerCheck.directChild).toBe(true);
    await expect(staleNote).toBeInViewport();
    // The pane auto-scrolls to the newest message; `absolute` passed every
    // assertion above yet sat thousands of pixels off-screen there. The note has
    // to survive the scrolled reading state, with Retry reachable for another try.
    const scrolledToNewest = await staleNote.evaluate((note) => {
      const scroller = note.closest(".overflow-y-auto") as HTMLElement;
      scroller.scrollTop = scroller.scrollHeight;
      return scroller.scrollTop;
    });
    expect(scrolledToNewest).toBeGreaterThan(0);
    await expect(staleNote).toBeInViewport();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByText("shipping friday").first()).toBeVisible();
    // `text-destructive` stays reserved for the empty list, where nothing loaded.
    await expect(page.getByText("Could not load messages.")).toHaveCount(0);

    mode = "ok";
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(staleNote).toHaveCount(0);
  });

  // The dead end — a failure with no cached rows — has no stale note to
  // carry a Retry button, so it carries its own Try again: with
  // refetchOnWindowFocus off, a refused load otherwise waits for a remount,
  // navigation or reload.
  test("Try again recovers the dead-end failure into the loaded messages", async ({ page }) => {
    await mockApi(page, { signedIn: true, lists: { conversations: [CONVERSATION] } });

    let attempts = 0;
    let succeed = false;
    await page.route(MESSAGES, async (route) => {
      attempts += 1;
      if (succeed) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MESSAGE_ROWS),
        });
      }
      return route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Boom" }),
      });
    });

    await page.goto("/inbox");
    await page.getByRole("button", { name: /Release plan/ }).click();

    await expect(page.getByText("Could not load messages.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    const before = attempts;
    succeed = true;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("shipping friday").first()).toBeVisible();
    await expect(page.getByText("Could not load messages.")).toHaveCount(0);
    // The click drove new request(s): the recovery is the query refetching,
    // not rows arriving from anywhere else.
    expect(attempts).toBeGreaterThan(before);
  });
});
