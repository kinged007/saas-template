// Manual check that every composer toolbar icon button exposes an accessible name.
// This repo has no web test runner and no CI job for it: start the dev stack
// (`make dev`, web on :5173), then run `npm run check:a11y-toolbar` by hand.
// Env: WEB_URL (default http://localhost:5173), EMAIL / PASSWORD (seeded demo login).
import { chromium } from "playwright";

const WEB_URL = process.env.WEB_URL || "http://localhost:5173";
const EMAIL = process.env.EMAIL || "admin@example.com";
const PASSWORD = process.env.PASSWORD || "password";

// The names the toolbar is expected to announce, in visual order.
const EXPECTED = [
  "Bold",
  "Italic",
  "Inline code",
  "Code block",
  "Bullet list",
  "Ordered list",
  "Quote",
  "Link",
];

const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const failures = [];

try {
  const page = await browser.newPage();
  page.setDefaultTimeout(30000);
  await page.goto(`${WEB_URL}/login`);

  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.includes("/login")).catch(() => {
    throw new Error(`login failed for ${EMAIL} — set EMAIL / PASSWORD to a seeded account`);
  });

  await page.goto(`${WEB_URL}/inbox`);
  await page.getByRole("button", { name: "Compose", exact: true }).click();

  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const toolbar = dialog.getByRole("toolbar", { name: "Formatting" });
  if ((await toolbar.count()) === 0) {
    failures.push('composer has no role="toolbar" named "Formatting"');
  }

  const buttons = await toolbar.getByRole("button").evaluateAll((nodes) =>
    nodes.map((b) => ({ title: b.getAttribute("title"), name: b.getAttribute("aria-label") })),
  );
  console.log("toolbar buttons:", JSON.stringify(buttons));

  const unnamed = buttons.filter((b) => !b.name);
  if (unnamed.length) {
    failures.push(`${unnamed.length} of ${buttons.length} toolbar buttons have no aria-label`);
  }
  // How an automated check has to reach them: by role and accessible name.
  for (const expected of EXPECTED) {
    if ((await toolbar.getByRole("button", { name: expected, exact: true }).count()) !== 1) {
      failures.push(`no toolbar button is reachable by role+name "${expected}"`);
    }
  }

  // The accessible names the browser computes, not just our attributes.
  if (await toolbar.count()) {
    console.log("accessibility tree:\n" + (await toolbar.ariaSnapshot()));
  }
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`FAIL: ${failures.length} problem(s)\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log(`PASS: ${EXPECTED.length} expected names all resolve, no unnamed button`);
