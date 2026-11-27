// API contract: each line fails `tsc -b` when the backend's response schema (from the generated
// schema.gen.ts) no longer fits the type the frontend reads it into, e.g. a renamed or removed field.
// Add a line when you type a new request<...>() against an endpoint with a response model and the
// frontend type is hand-written; a type declared as Served<S["..."]> in types.ts needs no line.
import type { Me } from "../lib/reviewKeys";
import type { BarrierValue, CompanyTransition, DataPointSchema, EmergingThemesScheduleConfig, QAAnswer, S, Served } from "../types";

type Satisfies<Backend extends Frontend, Frontend> = [Backend, Frontend];
// The backend types these fields loosely (plain dicts, a list[str]); the frontend's narrower
// type is taken on trust until the backend models them.
type QAAnswerServed = Served<S["QAAnswer"]> & { spec: { date_range: [string, string] | null } | null };
type TransitionBarrierServed = Omit<Served<S["BarrierOut"]>, "values"> & { values: BarrierValue[] };
type TransitionServed = Omit<Served<S["TransitionOut"]>, "actions"> & {
  actions: (Omit<Served<S["ActionOut"]>, "barriers"> & { barriers: TransitionBarrierServed[] })[];
};

export type ApiContract = [
  Satisfies<Served<S["DataPointSchema"]>, DataPointSchema>,
  Satisfies<Served<S["EmergingThemesScheduleConfig"]>, EmergingThemesScheduleConfig>,
  Satisfies<Served<S["Principal"]>, Me>,
  Satisfies<QAAnswerServed, QAAnswer>,
  Satisfies<TransitionServed, CompanyTransition>,
];
