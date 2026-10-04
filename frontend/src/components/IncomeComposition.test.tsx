import type { ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { IncomeComposition, compositionPercentage } from "@/components/IncomeComposition";

const included = Array.from({ length: 6 }, (_, index) => ({
  category_id: index + 1,
  category_name: `收入分类${index + 1}`,
  amount: index === 0 ? 50 : 10,
}));
const excluded = Array.from({ length: 6 }, (_, index) => ({
  category_id: index + 11,
  category_name: `其他数据${index + 1}`,
  amount: 5,
}));

function renderComposition(props: Partial<ComponentProps<typeof IncomeComposition>> = {}) {
  return render(
    <IncomeComposition
      included={included}
      excluded={excluded}
      totalIncome={100}
      {...props}
    />,
  );
}

it("shows five rows per group initially and expands each group independently", async () => {
  const user = userEvent.setup();
  renderComposition();

  expect(screen.getByText("收入分类5")).toBeInTheDocument();
  expect(screen.queryByText("收入分类6")).not.toBeInTheDocument();
  expect(screen.getByText("其他数据5")).toBeInTheDocument();
  expect(screen.queryByText("其他数据6")).not.toBeInTheDocument();
  expect(screen.getByText("50.0%")).toBeInTheDocument();
  expect(screen.getByText("其他数据1").parentElement).not.toHaveTextContent("%");

  await user.click(screen.getByRole("button", { name: /^展开收入分类/ }));

  expect(screen.getByText("收入分类6")).toBeInTheDocument();
  expect(screen.queryByText("其他数据6")).not.toBeInTheDocument();
});

it("shows a valid empty composition when total income is zero", () => {
  renderComposition({ included: [], excluded: [], totalIncome: 0 });

  expect(screen.getByRole("region", { name: "收入构成" })).toHaveTextContent("暂无收入构成");
});

it("shows only the groups that contain rows and uses the domain term other data", () => {
  const { rerender } = renderComposition({ excluded: [] });

  expect(screen.getByRole("region", { name: "收入分类" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "其他数据" })).not.toBeInTheDocument();
  expect(screen.queryByRole("separator")).not.toBeInTheDocument();

  rerender(
    <IncomeComposition
      included={[]}
      excluded={excluded}
      totalIncome={0}
    />,
  );

  expect(screen.getByRole("region", { name: "收入分类" })).toBeInTheDocument();
  expect(screen.getByText("暂无分类金额")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "其他数据" })).toBeInTheDocument();
  expect(screen.getByRole("separator")).toBeInTheDocument();
  expect(screen.queryByText("未计入总额")).not.toBeInTheDocument();
  expect(screen.queryByText(/历史总额记录/)).not.toBeInTheDocument();
});

it("shows 100 percent for a single item and no proportions for zero income", () => {
  const { rerender } = renderComposition({ included: [included[0]], excluded: [], totalIncome: 50 });

  expect(screen.getByText("100.0%")).toBeInTheDocument();

  rerender(
    <IncomeComposition
      included={included}
      excluded={[]}
      totalIncome={0}
    />,
  );

  expect(screen.queryByTestId("composition-proportion")).not.toBeInTheDocument();
});

it("rounds composition percentages from whole amounts", () => {
  expect(compositionPercentage(1, 3)).toBe("33.3%");
});

it("explains the entire summary denominator and keeps special income visible when collapsed", () => {
  renderComposition({
    included: [...included,
      { category_id: null, category_name: "未分类营业额", amount: 100 },
      { category_id: null, category_name: "公司结算", amount: 300 }],
    totalIncome: 500,
  });
  expect(screen.getByLabelText("收入分类1 占比 10.0%")).toBeInTheDocument();
  expect(screen.getByLabelText("未分类营业额 占比 20.0%")).toBeInTheDocument();
  expect(screen.getByLabelText("公司结算 占比 60.0%")).toBeInTheDocument();
  expect(screen.getByText("收入构成合计").parentElement).toHaveTextContent("€500");
});
