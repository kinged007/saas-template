import type { NotificationProvider } from "@refinedev/core";
import { toast } from "sonner";
import { UndoableNotification } from "@/components/refine-ui/notification/undoable-notification";

// refine builds every error title as "<what happened> (status code: N)" from
// `err.statusCode`, evaluating the template even when no request ever produced
// a response (offline, DNS failure, CORS rejection, abort) — that case carries
// the 0 sentinel. There is no status to report for it, so drop the whole
// parenthetical instead of showing a code that never existed.
const HTTP_STATUS_SUFFIX = /^(.*) \(status code: (\d+)\)$/;
const errorTitle = (message: string) => {
  const match = HTTP_STATUS_SUFFIX.exec(message);
  return match && !/^\d{3}$/.test(match[2]) ? match[1] : message;
};

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
