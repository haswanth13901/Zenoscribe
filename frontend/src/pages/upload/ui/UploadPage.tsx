import type { ReactElement } from "react";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import { UploadPanel } from "@/features/transcribe/ui/UploadPanel";

// Full-page replacement for the old ?upload=1 panel RecorderPage/AdminPage
// used to render on top of their own content (Recorder's "Press Start and
// speak." placeholder, Admin's Users/Recordings tabs) - now its own route,
// so the batch-transcribe form is the only thing on screen. UploadPanel
// itself is unchanged (still used, unmodified, by nothing else now that
// this is the only mount point) - "Reset" clears the form in place instead
// of navigating away.
export function UploadPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;

  return (
    <AppLayout user={user}>
      <UploadPanel open />
    </AppLayout>
  );
}
