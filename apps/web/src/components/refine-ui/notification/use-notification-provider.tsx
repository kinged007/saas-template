import type { NotificationProvider } from "@refinedev/core";
import { toast } from "sonner";
import { errorTitle } from "@/components/refine-ui/notification/error-title";
import { isReadFailure } from "@/components/refine-ui/notification/read-failure";
import { UndoableNotification } from "@/components/refine-ui/notification/undoable-notification";

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
          // A failed read is reported by the view that renders it — a toast on
          // top of it is the same refusal said twice, with two different
          // messages. Mutations keep theirs: an action has no in-body state.
          if (isReadFailure({ type, key })) return;
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
