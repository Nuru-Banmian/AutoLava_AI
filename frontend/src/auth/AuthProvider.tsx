import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useContext } from "react";

import { api, ApiError } from "@/api/client";
import type { User } from "@/api/types";

export const authQueryKey = ["auth", "me"] as const;

interface LoginInput {
  username: string;
  password: string;
  remember: boolean;
}

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  error: Error | null;
  login(input: LoginInput): Promise<User>;
  logout(): Promise<void>;
  isLoggingIn: boolean;
  isLoggingOut: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: authQueryKey,
    queryFn: async () => {
      try {
        return await api<User>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
  });
  const loginMutation = useMutation({
    mutationFn: (input: LoginInput) =>
      api<User>("/auth/login", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: (user) => queryClient.setQueryData(authQueryKey, user),
  });
  const logoutMutation = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => queryClient.setQueryData(authQueryKey, null),
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
