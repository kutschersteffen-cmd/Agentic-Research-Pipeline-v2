import test from "node:test";
import assert from "node:assert/strict";
import { apiMessage, formatValidationErrors } from "../src/lib/apiError.ts";

test("apiMessage drops the status prefix and keeps our message", () => {
  assert.equal(apiMessage(new Error("502: Upstream failed: boom")), "Upstream failed: boom");
});

test("formatValidationErrors handles pydantic objects and plain strings", () => {
  assert.equal(formatValidationErrors(["unknown dataset x", "too many charts"]), "unknown dataset x; too many charts");
  assert.equal(
    formatValidationErrors([{ loc: ["body", "plan", "title"], msg: "Value error, bad" }, { msg: "oops" }]),
    "plan › title: bad; oops",
  );
});
