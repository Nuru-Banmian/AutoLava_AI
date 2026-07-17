import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useContext } from "react";

import { api, ApiError } from "@/api/client";
import type { AuthenticatedUser } from "@/api/types";

export const authQueryKey = ["auth", "me"] as const;

interface LoginInput {
  username: string;
  password: string;
  remember: boolean;
}

interface AuthContextValue {
  user: AuthenticatedUser | null;
  isLoading: boolean;
  error: Error | null;
  login(input: LoginInput): Promise<AuthenticatedUser>;
  logout(): Promise<void>;
  isLoggingIn: boolean;
  isLoggingOut: boolean;
  logoutError: Error | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  async function removeUserQueries() {
    const userQuery = (query: { queryKey: readonly unknown[] }) => query.queryKey[0] !== "auth";
    await queryClient.cancelQueries({ predicate: userQuery });
    queryClient.removeQueries({ predicate: userQuery });
  }
  const me = useQuery({
    queryKey: authQueryKey,
    queryFn: async () => {
      try {
        return await api<AuthenticatedUser>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
  });
  const loginMutation = useMutation({
    onMutate: () => queryClient.cancelQueries({ queryKey: authQueryKey, exact: true }),
    mutationFn: (input: LoginInput) =>
      api<AuthenticatedUser>("/auth/login", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: async (user) => {
      await removeUserQueries();
      queryClient.setQueryData(authQueryKey, user);
    },
  });
  const logoutMutation = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: async () => {
      await removeUserQueries();
      queryClient.setQueryData(authQueryKey, null);
    },
  });

  return (
    <AuthContext.Provider
      value={{
        user: me.data ?? null,
        isLoading: me.isLoading,
        error: me.error,
        login: loginMutation.mutateAsync,
        logout: logoutMutation.mutateAsync,
        isLoggingIn: loginMutation.isPending,
        isLoggingOut: logoutMutation.isPending,
        logoutError: logoutMutation.error,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
