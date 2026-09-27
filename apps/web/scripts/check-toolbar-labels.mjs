// Check that every composer toolbar icon button exposes an accessible name.
//   node scripts/check-toolbar-labels.mjs
// Env: WEB_URL (default http://localhost:5273), EMAIL / PASSWORD (seeded demo login).
import { chromium } from "playwright";

const WEB_URL = process.env.WEB_URL || "http://localhost:5273";
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

  if (await page.getByLabel("Email").count()) {
    await page.getByLabel("Email").fill(EMAIL);
    await page.getByLabel(/password/i).fill(PASSWORD);
    await page.getByRole("button", { name: /sign in|log in/i }).click();
  } else {
    await page.getByLabel("Email address").fill(EMAIL);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
  }
  await page.waitForURL((u) => !u.pathname.includes("/login"));

  await page.goto(`${WEB_URL}/inbox`);
  await page.getByRole("button", { name: "Compose" }).first().click();

  // The toolbar is the bottom-bordered strip of the editor wrapper.
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const toolbar = dialog.locator("div.rounded-md > div.border-b");

  const buttons = await toolbar.getByRole("button").evaluateAll((nodes) =>
    nodes.map((b) => ({ title: b.getAttribute("title"), name: b.getAttribute("aria-label") })),
  );
  console.log("toolbar buttons:", JSON.stringify(buttons));

  const unnamed = buttons.filter((b) => !b.name);
  if (unnamed.length) {
    failures.push(`${unnamed.length} of ${buttons.length} toolbar buttons have no aria-label`);
  }
  if (buttons.length !== EXPECTED.length) {
    failures.push(`expected ${EXPECTED.length} toolbar buttons, found ${buttons.length}`);
  }
  // How an automated check has to reach them: by role and accessible name.
  for (const expected of EXPECTED) {
    if ((await toolbar.getByRole("button", { name: expected, exact: true }).count()) !== 1) {
      failures.push(`no toolbar button is reachable by role+name "${expected}"`);
    }
  }

  // The accessible names the browser computes, not just our attributes.
  console.log("accessibility tree:\n" + (await toolbar.ariaSnapshot()));
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`FAIL: ${failures.length} problem(s)\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log(`PASS: ${EXPECTED.length} toolbar buttons, all named`);
