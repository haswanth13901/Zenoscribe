import { baseApi } from "@/shared/api/baseApi";
import type { Recording, RecordingsQuery } from "@/entities/recording/model/types";

export const recordingsApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getRecordings: builder.query<Recording[], RecordingsQuery>({
      query: (params) => ({ url: "/recordings", params }),
      providesTags: ["Recordings"],
    }),
    getTranscript: builder.query<{ id: string; text: string }, string>({
      query: (id) => `/recordings/${id}/transcript`,
    }),
    deleteRecording: builder.mutation<{ ok: boolean }, string>({
      query: (id) => ({ url: `/recordings/${id}`, method: "DELETE" }),
      // Also invalidates "Users": on /admin, deleting a recording changes
      // the owning user's recording_count shown in the Users tab (matches
      // admin.html's delRec() refreshing both loadRecs() and loadUsers()).
      // A harmless no-op cache tag for /recordings (MyRecordingsPage.tsx),
      // which never subscribes to anything "Users"-tagged.
      invalidatesTags: ["Recordings", "Users"],
    }),
  }),
});

export const { useGetRecordingsQuery, useLazyGetTranscriptQuery, useDeleteRecordingMutation } =
  recordingsApi;
