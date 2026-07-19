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
      classifiedIncludedTotal={100}
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

it("omits the entire composition region when neither group has rows", () => {
  renderComposition({ included: [], excluded: [] });

  expect(screen.queryByRole("region", { name: "收入构成" })).not.toBeInTheDocument();
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
      classifiedIncludedTotal={0}
    />,
  );

  expect(screen.queryByRole("region", { name: "收入分类" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "其他数据" })).toBeInTheDocument();
  expect(screen.getByRole("separator")).toBeInTheDocument();
  expect(screen.queryByText("未计入总额")).not.toBeInTheDocument();
  expect(screen.queryByText(/历史总额记录/)).not.toBeInTheDocument();
});

it("does not render proportion bars for a single category or zero classified total", () => {
  const { rerender } = renderComposition({ included: [included[0]], excluded: [], classifiedIncludedTotal: 50 });

  expect(screen.queryByTestId("composition-proportion")).not.toBeInTheDocument();

  rerender(
    <IncomeComposition
      included={included}
      excluded={[]}
      classifiedIncludedTotal={0}
    />,
  );

  expect(screen.queryByTestId("composition-proportion")).not.toBeInTheDocument();
});

it("rounds composition percentages from whole amounts", () => {
  expect(compositionPercentage(1, 3)).toBe("33.3%");
});
