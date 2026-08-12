import { baseApi } from "../../api/baseApi";

export interface TranscribeTurn {
  text: string;
}

export interface TranscribeResponse {
  turns: TranscribeTurn[];
}

export interface TranscribeTranslateArgs {
  file: File;
  /** Omitted for a plain transcribe - POST /api/transcribe/translate with no
   * target_language behaves like POST /api/transcribe, which is the
   * original upload.js's own documented, intentional behavior (its plain
   * "Transcribe" button always posts to /transcribe/translate). Ported
   * as-is, not "fixed" - this is deliberate reuse, not a bug. */
  targetLanguage?: string;
}

export const transcribeApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    transcribeTranslate: builder.mutation<TranscribeResponse, TranscribeTranslateArgs>({
      query: ({ file, targetLanguage }) => {
        const formData = new FormData();
        formData.append("file", file, file.name);
        const qs = targetLanguage ? `?target_language=${encodeURIComponent(targetLanguage)}` : "";
        return { url: `/transcribe/translate${qs}`, method: "POST", body: formData };
      },
    }),
  }),
});

export const { useTranscribeTranslateMutation } = transcribeApi;
