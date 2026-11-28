// Property-based tests for the base64url helpers. Many random inputs are made by fast-check for each property, and if
// a property fails, the smallest input that fails is reported with the seed to repeat the run.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { fromBase64url, toBase64url } from "./webauthn";

// A fixed number of runs, so that the tests take about the same time on each run.
const RUNS = { numRuns: 200 };
const BASE64URL = /^[A-Za-z0-9_-]*$/;
// Characters that atob accepts, as well as the base64url ones: standard base64, padding and ASCII white space.
const ACCEPTED_BY_ATOB = new Set([..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_+/=", " ", "\t", "\n", "\f", "\r"]);
const BASE64URL_CHARACTER = fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_");

const bytesOf = (buffer: ArrayBuffer) => Array.from(new Uint8Array(buffer));
const bufferOf = (bytes: Uint8Array) => bytes.slice().buffer;

/** The name of the error that fromBase64url throws for this text, or undefined if it throws nothing. */
function decodingError(text: string): string | undefined {
  try {
    fromBase64url(text);
    return undefined;
  } catch (error) {
    return (error as Error).name;
  }
}

describe("base64url properties", () => {
  it("gives back the same bytes after encoding and decoding", () => {
    fc.assert(
      fc.property(fc.uint8Array({ maxLength: 512 }), (bytes) => {
        expect(bytesOf(fromBase64url(toBase64url(bufferOf(bytes))))).toEqual(Array.from(bytes));
      }),
      RUNS,
    );
  });

  it("writes only base64url characters, with no padding, four characters for three bytes", () => {
    fc.assert(
      fc.property(fc.uint8Array({ maxLength: 512 }), (bytes) => {
        const text = toBase64url(bufferOf(bytes));
        expect(text).toMatch(BASE64URL);
        expect(text).not.toMatch(/[+/=]/);
        expect(text).toHaveLength(Math.ceil((bytes.length * 4) / 3));
      }),
      RUNS,
    );
  });

  it("reads standard base64 with padding as well, because atob accepts it", () => {
    fc.assert(
      fc.property(fc.uint8Array({ maxLength: 512 }), (bytes) => {
        const standard = btoa(String.fromCharCode(...bytes));
        expect(bytesOf(fromBase64url(standard))).toEqual(Array.from(bytes));
      }),
      RUNS,
    );
  });

  it("throws InvalidCharacterError for text with a character that is not base64", () => {
    const outsider = fc.string({ unit: "binary", minLength: 1, maxLength: 1 }).filter((character) => !ACCEPTED_BY_ATOB.has(character));
    fc.assert(
      fc.property(fc.string({ unit: BASE64URL_CHARACTER }), outsider, fc.string({ unit: BASE64URL_CHARACTER }), (before, character, after) => {
        expect(decodingError(before + character + after)).toBe("InvalidCharacterError");
      }),
      RUNS,
    );
  });

  it("throws InvalidCharacterError for base64url text that is one character longer than a multiple of four", () => {
    const tooLong = fc.string({ unit: BASE64URL_CHARACTER, maxLength: 200 }).filter((text) => text.length % 4 === 1);
    fc.assert(
      fc.property(tooLong, (text) => {
        expect(decodingError(text)).toBe("InvalidCharacterError");
      }),
      RUNS,
    );
  });
});
