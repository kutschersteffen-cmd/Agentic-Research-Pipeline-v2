/** Our API's message without the "502: " status prefix. Never a raw body: `request` only ever
 * throws our own `detail` text (or a status line). */
export const apiMessage = (e: unknown): string =>
  (e instanceof Error ? e.message : String(e)).replace(/^\d{3}:\s*/, "");

/** FastAPI's 422 body: `detail` is a list of {loc, msg} objects (pydantic) or of plain strings.
 * Rendered as "spec › screens: msg" / "problem; problem". */
export function formatValidationErrors(errors: ({ loc?: (string | number)[]; msg?: string } | string)[]): string {
  return errors
    .map((e) => {
      if (typeof e === "string") return e;
      const where = (e.loc ?? []).filter((part) => part !== "body").join(" › ");
      const msg = (e.msg ?? "invalid").replace(/^Value error, /, "");
      return where ? `${where}: ${msg}` : msg;
    })
    .join("; ");
}
