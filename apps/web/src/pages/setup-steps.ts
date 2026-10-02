export type SetupStep = {
  done: boolean;
  title: string;
  hint: string;
  to: string;
  cta: string;
};

/**
 * The steps of the dashboard "Get set up" card, limited to what the identity
 * may actually do. A step it has no permission for is dropped rather than
 * shown as unfinished: its call to action leads to a route the backend
 * refuses, and leaving it in keeps the card on screen for good once every
 * step the user may do is done, with the manual dismiss as the only way out.
 *
 * A permission that has not resolved yet counts as missing (`useCan` returns
 * undefined while it loads) — rendering an action that disappears a tick later
 * reads worse than the brief omission.
 *
 * ponytail: a step is either present and actionable or absent. Add a
 * "not available to your role" row if a card ever has to explain an omission.
 */
export function setupSteps({
  canInvite,
  invitationCount,
  canCreateKey,
  apiKeyCount,
}: {
  canInvite?: boolean;
  invitationCount: number;
  canCreateKey?: boolean;
  apiKeyCount: number;
}): SetupStep[] {
  const steps: SetupStep[] = [];
  if (canInvite === true) {
    steps.push({
      done: invitationCount > 0,
      title: "Invite your team",
      hint: "Members get workspace access by role.",
      to: "/members",
      cta: "Invite",
    });
  }
  if (canCreateKey === true) {
    steps.push({
      done: apiKeyCount > 0,
      title: "Create an API key",
      hint: "Automate with scoped machine credentials.",
      to: "/api-keys/create",
      cta: "Create key",
    });
  }
  return steps;
}