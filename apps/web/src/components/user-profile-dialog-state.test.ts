import assert from "node:assert/strict";
import { test } from "node:test";

import type { UserProfile } from "@/types";

import { profileBodyState } from "./user-profile-dialog-state.ts";

const preloaded: UserProfile = {
  id: "u2",
  user_id: "u2",
  custom_data: {},
  first_name: "Ada",
  last_name: "Lovelace",
  email: "ada@example.com",
  bio: "first programmer",
};

test("a failed load keeps preloaded data instead of the dead end", () => {
  assert.equal(
    profileBodyState({
      isLoading: false,
      isError: true,
      profile: preloaded,
      fallback: { preloaded, email: "ada@example.com" },
    }),
    "profile",
  );
});

test("failed loads with no data and no preloaded fallback hit the dead end", () => {
  assert.equal(
    profileBodyState({ isLoading: false, isError: true, profile: null, fallback: null }),
    "dead-end",
  );
  assert.equal(
    profileBodyState({ isLoading: false, isError: true, profile: null, fallback: undefined }),
    "dead-end",
  );
});

test("a failed load still renders partial fallback row fields", () => {
  assert.equal(
    profileBodyState({
      isLoading: false,
      isError: true,
      profile: null,
      fallback: { display_name: "Ada", email: "ada@example.com", avatar_url: null },
    }),
    "profile",
  );
});

test("without an error, nothing to show is the empty state", () => {
  assert.equal(
    profileBodyState({ isLoading: false, isError: false, profile: null, fallback: null }),
    "empty",
  );
  assert.equal(
    profileBodyState({ isLoading: true, isError: false, profile: preloaded, fallback: { preloaded } }),
    "loading",
  );
});
