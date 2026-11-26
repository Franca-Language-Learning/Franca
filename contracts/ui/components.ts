/**
 * The component contract (story E01-002): the props of the shared interface components, agreed before the
 * interface lanes work in parallel. The components in client/src/components/ will be built to these types
 * (stories E13-002 to E13-004), and the design work uses the same names.
 *
 * Sources: design/interface-round-5.md (design language, EN marks, explanations inside a sentence) and
 * design/backend-and-technology-decisions.md (interface text, layout rules), in the project documents.
 *
 * These layout rules apply to all the components:
 * - Text containers have no fixed height, at most a minimum height.
 * - Children that hold text have min-width: 0 and overflow-wrap: anywhere, so long Dutch compounds wrap.
 * - Sizes are in rem and clamp(), and layout changes with container queries.
 * - A label, its control and its EN mark wrap as one unit.
 * - There is room for English up to 40% longer than the Dutch. This is tested with a pseudo-language that has
 *   its text stretched by 40%.
 */

import type { ReactNode } from "react";

// --- Interface text

/** A key in the message catalogues. Every visible string comes from a key, looked up in the course language and in English. */
export type MessageKey = string & { readonly __brand: "MessageKey" };

/** Values for an ICU message (plurals, numbers, dates and names). */
export type MessageValues = Record<string, string | number | Date>;

/**
 * How English is shown for a piece of target-language text when its EN mark is pressed:
 * - label: the label is replaced by its English
 * - sentence: the English is shown under the sentence
 */
export type TextKind = "label" | "sentence";

/**
 * The learner's setting for EN marks (Settings, round 5 decision R7):
 * - everywhere: a mark on every element
 * - content-only: marks on lesson content, none on the interface
 * - nowhere: no marks; English is still shown when the English switch in the header is on
 */
export type EnMarkSetting = "everywhere" | "content-only" | "nowhere";

/**
 * normal: the mark is in the Tab order.
 * faded: for labels that are on every screen (menu items, Begin, Open, Redo). The mark is at a third of its normal
 * opacity and out of the Tab order.
 */
export type EnMarkEmphasis = "normal" | "faded";

export interface TextProps {
  messageKey: MessageKey;
  values?: MessageValues;
  kind: TextKind;
  /** Whether the text is lesson content or interface text. The "content-only" EN mark setting depends on it. Default: "interface". */
  role?: "content" | "interface";
  enMark?: EnMarkEmphasis;
}

/** The switches in the header. They are per learner. */
export interface HeaderSwitches {
  /** English for every element: in place of labels, under sentences. */
  showAllEnglish: boolean;
  /** The grammar breakdown under every sentence (the G switch). */
  showAllBreakdowns: boolean;
}

// --- Design language

/**
 * Colours for the kinds of language:
 * - word: blue
 * - rule: ochre
 * - sound: terracotta
 * - english: cool grey
 */
export type LanguageKind = "word" | "rule" | "sound" | "english";

/**
 * Underlines and what they mean:
 * - link: ink, 1 px
 * - tappable-word: dotted blue, on a word that has a word card
 * - grammar-focus: ochre, 3 px
 * - sound-to-watch: dashed terracotta
 * - corrected: muted strikethrough on corrected learner text
 */
export type Underline = "link" | "tappable-word" | "grammar-focus" | "sound-to-watch" | "corrected";

/**
 * Surfaces:
 * - paper: content
 * - your-turn: the place where the learner answers, with the primary button in it; at most one per screen
 * - rule-wash: rule cards only, with an ochre top edge
 * - reference: a thin frame for reference panels
 */
export type Surface = "paper" | "your-turn" | "rule-wash" | "reference";

/**
 * There is no error state, and red is not used. A correct answer has an ink tick and the verdict word. A hint is a
 * strip with an ochre left edge.
 */
export type Feedback = "correct" | "hint";

/** Spacing steps, from the design tokens (story E13-002). */
export type Space = "3xs" | "2xs" | "xs" | "s" | "m" | "l" | "xl" | "2xl";

// --- Controls (on React Aria Components)

/** Text for a control: a message key, so the control has its EN mark. */
export interface ControlText {
  messageKey: MessageKey;
  values?: MessageValues;
  enMark?: EnMarkEmphasis;
}

export interface ButtonProps {
  label: ControlText;
  /**
   * primary: at most one per screen, in the your-turn surface.
   * secondary: a filled button for the other actions.
   * outline: a frame with at least 3:1 contrast against the background.
   * quiet: no frame.
   */
  variant: "primary" | "secondary" | "outline" | "quiet";
  onPress?: () => void;
  type?: "button" | "submit";
  isDisabled?: boolean;
  /** An icon before the label; decorative, so it has no text of its own. */
  icon?: ReactNode;
}

export interface LinkProps {
  label: ControlText;
  /** A path in the app, or an address outside it. */
  to: string;
  isExternal?: boolean;
}

export interface TextFieldProps {
  label: ControlText;
  description?: ControlText;
  errorMessage?: ControlText;
  value: string;
  onChange: (value: string) => void;
  /**
   * answer: a field for an answer in the target language. Spell check, autocorrect and autocapitalise are off,
   * and the field has the target language's lang attribute.
   */
  purpose: "answer" | "form";
  isRequired?: boolean;
  isDisabled?: boolean;
}

export interface Choice<Value extends string> {
  value: Value;
  label: ControlText;
  description?: ControlText;
}

/** A single choice from a few options, such as the rule depth (round 5 decision R8). */
export interface RadioGroupProps<Value extends string> {
  label: ControlText;
  options: readonly Choice<Value>[];
  value: Value;
  onChange: (value: Value) => void;
}

/** A single choice from many options. */
export interface SelectProps<Value extends string> {
  label: ControlText;
  options: readonly Choice<Value>[];
  value: Value | null;
  onChange: (value: Value) => void;
}

export interface CheckboxProps {
  label: ControlText;
  isSelected: boolean;
  onChange: (isSelected: boolean) => void;
}

/** An on or off setting that takes effect at once, such as the header switches. */
export interface SwitchProps {
  label: ControlText;
  isSelected: boolean;
  onChange: (isSelected: boolean) => void;
}

export interface Tab<Id extends string> {
  id: Id;
  label: ControlText;
  panel: ReactNode;
}

export interface TabsProps<Id extends string> {
  label: ControlText;
  tabs: readonly Tab<Id>[];
  selected: Id;
  onSelect: (id: Id) => void;
}

export interface DialogProps {
  title: ControlText;
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
  /** alertdialog: a dialog that needs an answer before the learner goes on. */
  role?: "dialog" | "alertdialog";
}

/** A small panel attached to an element, such as the word card. Opened by hover or focus on desktop, and by a tap on touch. */
export interface PopoverProps {
  trigger: ReactNode;
  label: ControlText;
  children: ReactNode;
}

// --- Layout primitives

/** Children one above the other. */
export interface StackProps {
  gap: Space;
  children: ReactNode;
}

/** Children side by side, wrapping onto new lines as needed. */
export interface ClusterProps {
  gap: Space;
  align?: "start" | "center" | "end" | "baseline";
  justify?: "start" | "center" | "end" | "space-between";
  children: ReactNode;
}

/** Columns at least minColumn wide. When two columns do not fit, there is one column. */
export interface GridProps {
  gap: Space;
  minColumn: `${number}rem`;
  children: ReactNode;
}

/** A region with one of the surfaces. */
export interface PanelProps {
  surface: Surface;
  /** A heading for the region. It gives the region an accessible name, so screen readers list it as a landmark. */
  label?: ControlText;
  children: ReactNode;
}

// --- The components, by name

/** The shared components and their props. A component in client/src/components/ will be typed with its entry here. */
export interface Components {
  Text: TextProps;
  Button: ButtonProps;
  Link: LinkProps;
  TextField: TextFieldProps;
  RadioGroup: RadioGroupProps<string>;
  Select: SelectProps<string>;
  Checkbox: CheckboxProps;
  Switch: SwitchProps;
  Tabs: TabsProps<string>;
  Dialog: DialogProps;
  Popover: PopoverProps;
  Stack: StackProps;
  Cluster: ClusterProps;
  Grid: GridProps;
  Panel: PanelProps;
}
