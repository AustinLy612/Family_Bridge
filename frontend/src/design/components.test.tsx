import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionButtons, ProgressBar, SelectCard } from ".";
import { Providers } from "../test/render";

describe("DecisionButtons (§2, §9.1C: declining as easy as accepting)", () => {
  it("renders accept and decline as adjacent buttons of the same size class", async () => {
    const onDecline = vi.fn();
    render(
      <DecisionButtons
        acceptLabel="Join"
        declineLabel="Not this time"
        onAccept={vi.fn()}
        onDecline={onDecline}
      />,
    );
    const [accept, decline] = screen.getAllByRole("button");
    expect(accept).toHaveTextContent("Join");
    expect(decline).toHaveTextContent("Not this time");
    expect(accept?.parentElement).toBe(decline?.parentElement);
    expect(accept?.className.replace("--primary", "")).toBe(decline?.className.replace("--secondary", ""));
    await userEvent.click(decline!);
    expect(onDecline).toHaveBeenCalledOnce();
  });
});

describe("SelectCard", () => {
  it("exposes selection through aria, not colour alone", () => {
    render(
      <div role="radiogroup" aria-label="modules">
        <SelectCard mode="radio" title="A" selected onSelect={vi.fn()} />
        <SelectCard mode="radio" title="B" selected={false} onSelect={vi.fn()} />
      </div>,
    );
    expect(screen.getByRole("radio", { name: "A" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "B" })).toHaveAttribute("aria-checked", "false");
  });
});

describe("ProgressBar", () => {
  it("is within-activity progress with a text label and clamps values", () => {
    render(
      <Providers>
        <ProgressBar current={9} total={5} />
      </Providers>,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "5");
    expect(bar).toHaveAttribute("aria-valuemax", "5");
  });
});
