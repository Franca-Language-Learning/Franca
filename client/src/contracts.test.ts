// Checks of the component contract in contracts/ui/components.ts. The type checks run in  pnpm typecheck;
// the type check fails if a line marked @ts-expect-error has no type error, which happens if the contract starts
// to allow a value it should reject.
import { describe, expectTypeOf, it } from "vitest";
import type { ButtonProps, Components, MessageKey, TextFieldProps, TextProps } from "../../contracts/ui/components";

const key = "home.title" as MessageKey;

describe("component contract", () => {
  it("lists the shared components", () => {
    expectTypeOf<keyof Components>().toEqualTypeOf<
      "Text" | "Button" | "Link" | "TextField" | "RadioGroup" | "Select" | "Checkbox" | "Switch" | "Tabs" | "Dialog" | "Popover" | "Stack" | "Cluster" | "Grid" | "Panel"
    >();
  });

  it("a plain string in place of a message key is a type error", () => {
    expectTypeOf<{ messageKey: MessageKey; kind: "label" }>().toMatchTypeOf<TextProps>();
    // @ts-expect-error A plain string is not a message key, so text has to come from the catalogues unless it is cast on purpose.
    const plain: TextProps = { messageKey: "Franca", kind: "label" };
    void plain;
  });

  it("a button has a catalogue label and one of the agreed variants", () => {
    const button: ButtonProps = { label: { messageKey: key }, variant: "primary" };
    void button;
    // @ts-expect-error There is no danger variant: red is not used.
    const red: ButtonProps = { label: { messageKey: key }, variant: "danger" };
    void red;
  });

  it("a text field has to be marked as an answer field or a form field", () => {
    expectTypeOf<TextFieldProps["purpose"]>().toEqualTypeOf<"answer" | "form">();
  });
});
