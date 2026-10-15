import { expect, test as base } from "playwright/test";

/**
 * The only `test` the specs import. An uncaught page error fails the test that
 * ran it, so a pane that throws on load cannot pass on partial render.
 */
export const test = base.extend<{ pageerrors: Error[] }>({
  pageerrors: [
    async ({ page }, use) => {
      const errors: Error[] = [];
      page.on("pageerror", (error) => errors.push(error));
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});
