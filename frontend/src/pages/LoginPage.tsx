import { type FormEvent, useState } from "react";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import { Navigate } from "react-router-dom";

import { friendlyApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function LoginPage() {
  const { user, isLoading, login, isLoggingIn } = useAuth();
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);

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
      setError(friendlyApiError(caught, "登录失败，请稍后重试"));
    }
  }

  return (
    <main className="flex min-h-screen w-full min-w-0 items-center justify-center overflow-x-hidden bg-slate-50 p-3 sm:p-6">
      <section className="grid w-full min-w-0 max-w-5xl overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-xl md:grid-cols-2">
        <div className="flex min-w-0 flex-col justify-between bg-gradient-to-br from-blue-700 to-blue-500 p-6 text-white sm:p-10">
          <div>
            <div className="mb-8 flex size-12 items-center justify-center rounded-xl bg-white/15">
              <ShieldCheck aria-hidden="true" className="size-7" />
            </div>
            <p className="text-sm font-semibold tracking-[0.2em] text-blue-100">AUTOLAVA</p>
            <h2 className="mt-3 text-2xl font-bold sm:text-3xl">让门店经营更简单</h2>
            <p className="mt-4 max-w-sm text-sm leading-6 text-blue-100">
              安全登录后即可查看经营数据、记录每日业务并管理门店。
            </p>
          </div>
          <p className="mt-10 text-xs text-blue-100">安全、清晰、随时可用</p>
        </div>

        <div className="min-w-0 p-6 sm:p-10">
          <div className="mb-8">
            <h1 className="text-2xl font-bold tracking-tight">登录</h1>
            <p className="mt-2 text-sm text-muted-foreground">欢迎回来，请输入账号信息</p>
          </div>

          <form className="space-y-5" onSubmit={submit}>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="username">用户名</label>
              <Input autoComplete="username" id="username" name="username" required />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="password">密码</label>
              <div className="relative min-w-0">
                <Input
                  autoComplete="current-password"
                  className="pr-12"
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  required
                />
                <Button
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground"
                  onClick={() => setShowPassword((value) => !value)}
                  size="icon"
                  type="button"
                  variant="ghost"
                >
                  {showPassword ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
                </Button>
              </div>
            </div>
            <label className="flex w-fit items-center gap-2 text-sm">
              <input className="size-4 accent-primary" name="remember" type="checkbox" />
              记住我
            </label>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button className="h-11 w-full" disabled={isLoggingIn} type="submit">
              {isLoggingIn ? "正在登录…" : "登录"}
            </Button>
          </form>
        </div>
      </section>
    </main>
  );
}
