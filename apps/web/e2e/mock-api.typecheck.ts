import type { Page } from "playwright/test";
import type { Identity } from "../src/types";
import { IDENTITY, mockApi } from "./mock-api";

export function checkIdentityContract(page: Page) {
  const identity: Identity = IDENTITY;
  void mockApi(page, { signedIn: true, identity });
  const { workspaces, ...withoutWorkspaces } = IDENTITY;
  // @ts-expect-error An identity must include workspaces.
  void mockApi(page, { signedIn: true, identity: withoutWorkspaces });
  // @ts-expect-error Workspace roles must be strings.
  void mockApi(page, { signedIn: true, identity: { ...IDENTITY, workspaces: [{ ...workspaces[0], role: 42 }] } });
}
