import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { Application } from "@/App";
import { createAppRouter } from "@/router";

const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "member", role: "user" })),
  http.get("/api/stores/accessible", () => HttpResponse.json([])),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPasswordPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<Application queryClient={queryClient} router={createAppRouter(["/account/password"])} />);
}

async function fillPasswords(current: string, password: string, confirmation: string) {
  fireEvent.change(await screen.findByLabelText("当前密码"), { target: { value: current } });
  fireEvent.change(screen.getByLabelText("新密码"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: confirmation } });
}

describe("AccountPasswordPage", () => {
  it("shows a mobile-safe form and rejects a mismatched confirmation in Chinese", async () => {
    let requests = 0;
    server.use(http.post("/api/auth/password", () => {
      requests += 1;
      return new HttpResponse(null, { status: 204 });
    }));
    renderPasswordPage();

    expect(await screen.findByRole("heading", { level: 1, name: "修改密码" })).toBeInTheDocument();
    const form = screen.getByRole("button", { name: "更新密码" }).closest("form");
    expect(form).toHaveClass("min-w-0", "w-full");
    await fillPasswords("OldPassword1", "NewPassword2", "Different3");
    fireEvent.submit(form!);

    expect(await screen.findByRole("alert")).toHaveTextContent("两次输入的新密码不一致");
    expect(requests).toBe(0);
  });

  it("changes the password and returns to More with a success status", async () => {
    let body: unknown;
    server.use(http.post("/api/auth/password", async ({ request }) => {
      body = await request.json();
      return new HttpResponse(null, { status: 204 });
    }));
    renderPasswordPage();

    await fillPasswords("OldPassword1", "NewPassword2", "NewPassword2");
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    expect(await screen.findByRole("heading", { level: 1, name: "更多" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("密码已更新");
    expect(body).toEqual({ current_password: "OldPassword1", new_password: "NewPassword2" });
  });

  it("shows a Chinese server error without echoing either password", async () => {
    server.use(http.post("/api/auth/password", () => (
      HttpResponse.json({ detail: "当前密码不正确" }, { status: 422 })
    )));
    renderPasswordPage();

    await fillPasswords("WrongPassword1", "NewPassword2", "NewPassword2");
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("当前密码不正确");
    expect(alert).not.toHaveTextContent("WrongPassword1");
    expect(alert).not.toHaveTextContent("NewPassword2");
  });

  it("disables submission while the password update is pending", async () => {
    let resolve!: () => void;
    server.use(http.post("/api/auth/password", async () => {
      await new Promise<void>((done) => { resolve = done; });
      return new HttpResponse(null, { status: 204 });
    }));
    renderPasswordPage();

    await fillPasswords("OldPassword1", "NewPassword2", "NewPassword2");
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "正在更新…" })).toBeDisabled());
    resolve();
  });
});
