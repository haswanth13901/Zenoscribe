import { baseApi } from "@/shared/api/baseApi";

export interface TranscribeTurn {
  speaker: string;
  text: string;
  /** Present only when a target language was requested - the translated
   * text for this turn, shown under the original. */
  translation?: string;
  start?: number | null;
  end?: number | null;
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
  /** Optional hint for how many distinct voices to expect. */
  numSpeakers?: number;
}

export const transcribeApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    transcribeTranslate: builder.mutation<TranscribeResponse, TranscribeTranslateArgs>({
      query: ({ file, targetLanguage, numSpeakers }) => {
        const formData = new FormData();
        formData.append("file", file, file.name);
        if (numSpeakers) formData.append("num_speakers", String(numSpeakers));
        const qs = targetLanguage ? `?target_language=${encodeURIComponent(targetLanguage)}` : "";
        return { url: `/transcribe/translate${qs}`, method: "POST", body: formData };
      },
    }),
  }),
});

export const { useTranscribeTranslateMutation } = transcribeApi;
