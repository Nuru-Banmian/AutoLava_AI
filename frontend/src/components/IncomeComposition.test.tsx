import type { ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { IncomeComposition, compositionPercentage } from "@/components/IncomeComposition";

const included = Array.from({ length: 6 }, (_, index) => ({
  category_id: index + 1,
  category_name: `收入分类${index + 1}`,
  amount: index === 0 ? "50.00" : "10.00",
}));
const excluded = Array.from({ length: 6 }, (_, index) => ({
  category_id: index + 11,
  category_name: `排除分类${index + 1}`,
  amount: "5.00",
}));

function renderComposition(props: Partial<ComponentProps<typeof IncomeComposition>> = {}) {
  return render(
    <IncomeComposition
      included={included}
      excluded={excluded}
      classifiedIncludedTotal="100.00"
      totalRevenue="100.00"
      {...props}
    />,
  );
}

it("shows five rows per group initially and expands each group independently", async () => {
  const user = userEvent.setup();
  renderComposition();

  expect(screen.getByText("收入分类5")).toBeInTheDocument();
  expect(screen.queryByText("收入分类6")).not.toBeInTheDocument();
  expect(screen.getByText("排除分类5")).toBeInTheDocument();
  expect(screen.queryByText("排除分类6")).not.toBeInTheDocument();
  expect(screen.getByText("50.0%")).toBeInTheDocument();
  expect(screen.getByText("排除分类1").parentElement).not.toHaveTextContent("%");

  await user.click(screen.getByRole("button", { name: /^展开收入分类/ }));

  expect(screen.getByText("收入分类6")).toBeInTheDocument();
  expect(screen.queryByText("排除分类6")).not.toBeInTheDocument();
});

it("does not render proportion bars for a single category or zero classified total", () => {
  const { rerender } = renderComposition({ included: [included[0]], excluded: [], classifiedIncludedTotal: "50.00" });

  expect(screen.queryByTestId("composition-proportion")).not.toBeInTheDocument();

  rerender(
    <IncomeComposition
      included={included}
      excluded={[]}
      classifiedIncludedTotal="0.00"
      totalRevenue="100.00"
    />,
  );

  expect(screen.queryByTestId("composition-proportion")).not.toBeInTheDocument();
});

it("rounds composition percentages from cents", () => {
  expect(compositionPercentage("1.00", "3.00")).toBe("33.3%");
});
