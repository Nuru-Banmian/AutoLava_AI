import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, friendlyApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function AccountPasswordPage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const currentPassword = String(data.get("current_password"));
    const newPassword = String(data.get("new_password"));
    const confirmation = String(data.get("confirmation"));
    setError("");

    if (newPassword !== confirmation) {
      setError("两次输入的新密码不一致");
      return;
    }

    setIsPending(true);
    try {
      await api<void>("/auth/password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setIsPending(false);
      navigate("/more", { replace: true, state: { status: "密码已更新" } });
    } catch (caught) {
      setError(friendlyApiError(caught, "密码更新失败，请稍后重试"));
      setIsPending(false);
    }
  }

  return (
    <section className="grid min-w-0 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">修改密码</h1>
        <p className="mt-1 text-sm text-muted-foreground">请输入当前密码，并设置至少 8 位的新密码。</p>
      </div>
      <form className="grid min-w-0 w-full max-w-lg gap-4 rounded-xl border border-blue-100 bg-background p-4 shadow-sm sm:p-6" onSubmit={submit}>
        <div className="grid min-w-0 gap-2">
          <label className="text-sm font-medium" htmlFor="current-password">当前密码</label>
          <Input autoComplete="current-password" id="current-password" maxLength={128} minLength={8} name="current_password" required type="password" />
        </div>
        <div className="grid min-w-0 gap-2">
          <label className="text-sm font-medium" htmlFor="new-password">新密码</label>
          <Input autoComplete="new-password" id="new-password" maxLength={128} minLength={8} name="new_password" required type="password" />
        </div>
        <div className="grid min-w-0 gap-2">
          <label className="text-sm font-medium" htmlFor="password-confirmation">确认新密码</label>
          <Input autoComplete="new-password" id="password-confirmation" maxLength={128} minLength={8} name="confirmation" required type="password" />
        </div>
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <Button className="w-full sm:w-fit" disabled={isPending} type="submit">
          {isPending ? "正在更新…" : "更新密码"}
        </Button>
      </form>
    </section>
  );
}
