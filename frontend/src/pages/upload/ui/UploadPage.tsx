import type { ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import { UploadPanel } from "@/features/transcribe/ui/UploadPanel";

// Full-page replacement for the old ?upload=1 panel RecorderPage/AdminPage
// used to render on top of their own content (Recorder's "Press Start and
// speak." placeholder, Admin's Users/Recordings tabs) - now its own route,
// so the batch-transcribe form is the only thing on screen. UploadPanel
// itself is unchanged (still used, unmodified, by nothing else now that
// this is the only mount point) - "Close" navigates back to /home.
export function UploadPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const navigate = useNavigate();

  return (
    <AppLayout user={user}>
      <UploadPanel open onClose={() => navigate("/home")} />
    </AppLayout>
  );
}
