import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import VoiceCall from "./VoiceCall";

it("unconfigured, it says so and names the fallback instead of offering a dead button", () => {
  // test-setup.ts stubs VITE_VAPI_* empty, so this asserts on a clean checkout —
  // where Vite tree-shakes the SDK out of the bundle entirely — and not on whatever
  // the developer happens to have in .env for a live demo.
  render(<VoiceCall />);

  expect(screen.getByText(/not configured/i)).toBeTruthy();
  expect(screen.getByText(/IVR line still books/i)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
