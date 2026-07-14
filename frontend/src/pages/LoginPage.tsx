import { type FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function LoginPage() {
  const { user, isLoading, login, isLoggingIn } = useAuth();
  const [error, setError] = useState("");

  if (isLoading) return <main className="flex min-h-screen items-center justify-center" role="status">正在加载…</main>;
  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setError("");
    try {
      await login({
        username: String(data.get("username")),
        password: String(data.get("password")),
        remember: data.get("remember") === "on",
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "登录失败，请稍后重试");
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader><CardTitle className="text-2xl">登录</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2"><label htmlFor="username">用户名</label><Input id="username" name="username" required /></div>
            <div className="space-y-2"><label htmlFor="password">密码</label><Input id="password" name="password" type="password" required /></div>
            <label className="flex items-center gap-2"><input name="remember" type="checkbox" />记住我</label>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button className="w-full" disabled={isLoggingIn} type="submit">{isLoggingIn ? "正在登录…" : "登录"}</Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
