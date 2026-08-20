import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import VoiceCall from "./VoiceCall";

it("unconfigured, it says so and names the fallback instead of offering a dead button", () => {
  // No VITE_VAPI_* in the test env — the same state a clean checkout builds in, where
  // Vite tree-shakes the SDK out of the bundle entirely.
  render(<VoiceCall />);

  expect(screen.getByText(/not configured/i)).toBeTruthy();
  expect(screen.getByText(/IVR line still books/i)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
