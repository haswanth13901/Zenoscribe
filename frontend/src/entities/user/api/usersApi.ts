import { baseApi } from "@/shared/api/baseApi";
import type { AdminUser, NewUserBody } from "@/entities/user/model/types";

export const usersApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getUsers: builder.query<AdminUser[], void>({
      query: () => "/admin/users",
      providesTags: ["Users"],
    }),
    createUser: builder.mutation<{ id: string; username: string; role: string }, NewUserBody>({
      query: (body) => ({ url: "/admin/users", method: "POST", body }),
      invalidatesTags: ["Users"],
    }),
    resetPassword: builder.mutation<{ ok: boolean }, { id: string; password: string }>({
      query: ({ id, password }) => ({
        url: `/admin/users/${id}/password`,
        method: "POST",
        body: { password },
      }),
      // No tag invalidation - a password reset doesn't change anything rendered.
    }),
    setActive: builder.mutation<{ ok: boolean }, { id: string; is_active: boolean }>({
      query: ({ id, is_active }) => ({
        url: `/admin/users/${id}/active`,
        method: "POST",
        body: { is_active },
      }),
      invalidatesTags: ["Users"],
    }),
    deleteUser: builder.mutation<{ ok: boolean; removed_recordings: number }, string>({
      query: (id) => ({ url: `/admin/users/${id}`, method: "DELETE" }),
      // Deleting a user cascades their recordings too.
      invalidatesTags: ["Users", "Recordings"],
    }),
  }),
});

export const {
  useGetUsersQuery,
  useCreateUserMutation,
  useResetPasswordMutation,
  useSetActiveMutation,
  useDeleteUserMutation,
} = usersApi;
