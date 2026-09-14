import { useCustom, useCustomMutation, useInvalidate } from "@refinedev/core";

import type { WebhookDelivery } from "../types";

export function useWebhookDeliveries(subscriptionId: string) {
  const { result, query } = useCustom<WebhookDelivery[]>({
    url: "webhooks/deliveries",
    method: "get",
    config: { query: { subscription_id: subscriptionId } },
  });
  return { result, query };
}

export function useWebhookRedeliver() {
  const invalidate = useInvalidate();
  const { mutate, mutation } = useCustomMutation();
  return {
    mutation,
    mutate: (deliveryId: string) =>
      mutate(
        {
          url: `webhooks/deliveries/${deliveryId}/redeliver`,
          method: "post",
          values: {},
          successNotification: {
            message: "Delivery queued",
            description: "The delivery will be retried shortly.",
            type: "success",
          },
        },
        {
          onSuccess: () =>
            invalidate({ resource: "webhooks", invalidates: ["list"] }),
        },
      ),
  };
}
