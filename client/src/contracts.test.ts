// Checks of the component contract in contracts/ui/components.ts. The type checks run in  pnpm typecheck;
// a @ts-expect-error line fails the type check if the contract stops refusing what it should refuse.
import { describe, expectTypeOf, it } from "vitest";
import type { ButtonProps, Components, MessageKey, TextFieldProps, TextProps } from "../../contracts/ui/components";

const key = "home.title" as MessageKey;

describe("component contract", () => {
  it("lists the shared components", () => {
    expectTypeOf<keyof Components>().toEqualTypeOf<
      "Text" | "Button" | "Link" | "TextField" | "RadioGroup" | "Select" | "Checkbox" | "Switch" | "Tabs" | "Dialog" | "Popover" | "Stack" | "Cluster" | "Grid" | "Panel"
    >();
  });

  it("needs a message key for visible text, not a plain string", () => {
    expectTypeOf<{ messageKey: MessageKey; kind: "label" }>().toMatchTypeOf<TextProps>();
    // @ts-expect-error A plain string is not a message key, so text cannot bypass the catalogues.
    const plain: TextProps = { messageKey: "Franca", kind: "label" };
    void plain;
  });

  it("gives a button a label from the catalogues and one of the agreed variants", () => {
    const button: ButtonProps = { label: { messageKey: key }, variant: "primary" };
    void button;
    // @ts-expect-error There is no danger variant: red is not used.
    const red: ButtonProps = { label: { messageKey: key }, variant: "danger" };
    void red;
  });

  it("asks every text field whether it takes an answer in the target language", () => {
    expectTypeOf<TextFieldProps["purpose"]>().toEqualTypeOf<"answer" | "form">();
  });
});
