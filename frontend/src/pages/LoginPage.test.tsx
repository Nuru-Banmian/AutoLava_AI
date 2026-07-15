import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { LoginPage } from "@/pages/LoginPage";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));

const login = vi.fn();

function renderLogin() {
  vi.mocked(useAuth).mockReturnValue({
    user: null,
    isLoading: false,
    error: null,
    login,
    logout: vi.fn(),
    isLoggingIn: false,
    isLoggingOut: false,
    logoutError: null,
  });
  return render(<MemoryRouter><LoginPage /></MemoryRouter>);
}

describe("LoginPage", () => {
  beforeEach(() => {
    login.mockReset();
  });

  it("shows a Chinese disabled-account message", async () => {
    login.mockRejectedValue(new ApiError(403, "Inactive user"));
    renderLogin();

    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "disabled" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Password123" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("这个账号已停用，请联系管理员");
  });

  it("toggles password visibility with an accessible button", () => {
    renderLogin();

    const password = screen.getByLabelText("密码");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");

    fireEvent.click(screen.getByRole("button", { name: "显示密码" }));
    expect(password).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "隐藏密码" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "隐藏密码" }));
    expect(password).toHaveAttribute("type", "password");
  });
});
