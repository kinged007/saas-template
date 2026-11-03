import type { NotificationProvider } from "@refinedev/core";
import { toast } from "sonner";
import { errorTitle } from "@/components/refine-ui/notification/error-title";
import { UndoableNotification } from "@/components/refine-ui/notification/undoable-notification";
import { MFA_REQUIRED_MESSAGE } from "@/utils/mfaRequired";

export function useNotificationProvider(): NotificationProvider {
  return {
    open: ({
      key,
      type,
      message,
      description,
      undoableTimeout,
      cancelMutation,
    }) => {
      switch (type) {
        case "success":
          toast.success(message, {
            id: key,
            description,
            richColors: true,
          });
          return;

        case "error":
          // The MFA gate redirects with its own toast (see the httpClient
          // interceptor); a generic one here would stack the same message.
          if (message === MFA_REQUIRED_MESSAGE) return;
          toast.error(errorTitle(message), {
            id: key,
            description,
            richColors: true,
          });
          return;

        case "progress": {
          const toastId = key || Date.now();

          toast(
            () => (
              <UndoableNotification
                message={message}
                description={description}
                undoableTimeout={undoableTimeout}
                cancelMutation={cancelMutation}
                onClose={() => toast.dismiss(toastId)}
              />
            ),
            {
              id: toastId,
              duration: (undoableTimeout || 5) * 1000,
              unstyled: true,
            },
          );
          return;
        }

        default:
          return;
      }
    },
    close: (id) => {
      toast.dismiss(id);
    },
  };
}
