import { baseApi } from "../../api/baseApi";

export interface Language {
  code: string;
  name: string;
}

export interface LanguagesResponse {
  languages: Language[];
  voices: string[];
}

// /api/languages is registered directly in server.py (not under
// routes_api.py's router), but the path still resolves correctly against
// baseApi's `${origin}/api` base. Reusable later by /translate's migration.
export const languagesApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getLanguages: builder.query<LanguagesResponse, void>({
      query: () => "/languages",
    }),
  }),
});

export const { useGetLanguagesQuery } = languagesApi;
