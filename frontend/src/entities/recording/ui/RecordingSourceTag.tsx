import type { ReactElement } from "react";
import { RECORDING_SOURCE_LABELS, type RecordingSource } from "../model/types";
import styles from "./RecordingSourceTag.module.css";

// Same pill treatment as UsersTable.module.css's role .tag - reused here
// (not imported from there since that module is scoped to the admin Users
// tab) so a recording's origin reads at a glance without opening a filter.
export function RecordingSourceTag({ source }: { source: RecordingSource }): ReactElement {
  return <span className={styles.tag}>{RECORDING_SOURCE_LABELS[source]}</span>;
}
