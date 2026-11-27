// Dates as the pages show them, in British English: 1 Dec 2026.
const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** The day of an ISO 8601 time from the server, such as 1 Dec 2026. */
export function formatDay(iso: string): string {
  return DAY.format(new Date(iso));
}
