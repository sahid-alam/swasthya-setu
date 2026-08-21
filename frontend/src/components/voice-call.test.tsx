import { render } from "@testing-library/react";
import { expect, it } from "vitest";

import VoiceCall from "./VoiceCall";

it("unconfigured, it offers nothing rather than a dead button or an env var", () => {
  // test-setup.ts stubs VITE_VAPI_* empty, so this asserts on a clean checkout — where
  // Vite tree-shakes the SDK out of the bundle entirely — and not on whatever the
  // developer happens to have in .env for a live demo.
  //
  // Nothing at all is the requirement, not a disabled button: this is a patient screen
  // now, the booking form below it works, and "Set VITE_VAPI_PUBLIC_KEY" is not a
  // sentence to put in front of someone standing in a corridor.
  const { container } = render(<VoiceCall lang="HI" />);

  expect(container).toBeEmptyDOMElement();
});
