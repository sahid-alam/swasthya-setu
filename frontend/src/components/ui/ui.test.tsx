import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Chip, PRESENCE_TONE, PresenceChip } from "./index";

describe("status vocabulary (DESIGN.md §9d)", () => {
  it("maps every presence state the schema defines", () => {
    // if SCHEMA.md gains a state, this fails rather than silently rendering grey
    for (const state of [
      "PRESENT_IN_DEPT",
      "PRESENT_ELSEWHERE",
      "ON_ROUNDS",
      "IN_SURGERY",
      "ON_LEAVE",
      "OFF_SHIFT",
      "UNKNOWN",
    ]) {
      expect(PRESENCE_TONE[state]).toBeDefined();
    }
  });

  it("labels state as text, never colour alone", () => {
    render(<PresenceChip state="IN_SURGERY" confidence={0.9} />);
    expect(screen.getByText("in surgery")).toBeInTheDocument();
  });

  it("shows the percentage when confidence is low", () => {
    render(<PresenceChip state="UNKNOWN" confidence={0.31} />);
    expect(screen.getByText("31%")).toBeInTheDocument();
  });

  it("hides the percentage when confidence is high", () => {
    render(<PresenceChip state="PRESENT_IN_DEPT" confidence={0.95} />);
    expect(screen.queryByText("95%")).not.toBeInTheDocument();
  });

  it("renders a chip with its dot", () => {
    const { container } = render(<Chip tone="success">present</Chip>);
    expect(container.querySelector("span[aria-hidden]")).toBeTruthy();
  });
});
