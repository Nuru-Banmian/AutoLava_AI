import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { LoginPage } from "@/pages/LoginPage";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));

const login = vi.fn();

function mockAuth(isLoggingIn = false) {
  vi.mocked(useAuth).mockReturnValue({
    user: null,
    isLoading: false,
    error: null,
    login,
    logout: vi.fn(),
    isLoggingIn,
    isLoggingOut: false,
    logoutError: null,
  });
}

function renderLogin() {
  mockAuth();
  return render(<MemoryRouter><LoginPage /></MemoryRouter>);
}

function contrastRatio(foreground: string, background: string) {
  const luminance = (hex: string) => {
    const channels = hex.match(/[a-f\d]{2}/gi)?.map((value) => Number.parseInt(value, 16) / 255) ?? [];
    const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
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

  it("uses an AA-compliant approved-blue brand palette", () => {
    renderLogin();

    const panel = screen.getByText("AUTOLAVA").closest("div.bg-gradient-to-br");
    expect(panel).toHaveClass("from-blue-950", "to-blue-800");
    expect(screen.getByText("安全登录后即可查看经营数据、记录每日业务并管理门店。"))
      .toHaveClass("text-blue-100");
    expect(screen.getByText("安全、清晰、随时可用")).toHaveClass("text-blue-100");

    const approvedBlue = { start: "#172554", end: "#1e40af", smallText: "#dbeafe" };
    expect(contrastRatio(approvedBlue.smallText, approvedBlue.start)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(approvedBlue.smallText, approvedBlue.end)).toBeGreaterThanOrEqual(4.5);
  });

  it("uses one page-level heading for the login form", () => {
    renderLogin();

    expect(screen.getByRole("heading", { level: 1, name: "登录" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading")).toHaveLength(1);
  });

  it("does not offer a remembered-login checkbox", () => {
    renderLogin();

    expect(screen.queryByLabelText("记住我")).not.toBeInTheDocument();
  });

  it("toggles password visibility from the keyboard with a dynamic accessible name", async () => {
    const user = userEvent.setup();
    renderLogin();

    const username = screen.getByLabelText("用户名");
    const password = screen.getByLabelText("密码");
    expect(username).toHaveAttribute("autocomplete", "username");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");

    await user.tab();
    expect(username).toHaveFocus();
    await user.tab();
    expect(password).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "显示密码" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(password).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "隐藏密码" })).toBeInTheDocument();

    await user.keyboard(" ");
    expect(password).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "显示密码" })).toHaveFocus();
  });

  it("disables the loading submit button to prevent duplicate login requests", async () => {
    login.mockImplementation(() => new Promise(() => {}));
    const view = renderLogin();

    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Password123" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(login).toHaveBeenCalledTimes(1);

    mockAuth(true);
    view.rerender(<MemoryRouter><LoginPage /></MemoryRouter>);
    const loadingButton = screen.getByRole("button", { name: "正在登录…" });
    expect(loadingButton).toBeDisabled();
    fireEvent.click(loadingButton);
    fireEvent.click(loadingButton);
    expect(login).toHaveBeenCalledTimes(1);
  });
});
