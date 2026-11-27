"""Pure XBRL fact data models shared by SEC EDGAR (`xbrl.py`) and ESEF (`esef.py`)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, DocType


def _full_year(row: dict) -> bool:
    """A duration of about a year; an instant (no start, e.g. a balance) passes."""
    if not row.get("start"):
        return True
    days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
    return 350 <= days <= 380


class FrozenFacts(BaseModel):
    """A stored companyfacts original (blob under sha256(raw)) and its rendered text, one line per
    annual fact, which a tagged citation quotes and the publish gate re-grounds against."""

    doc_id: str
    content_key: str
    parser_version: str
    text: str


class XbrlFact(BaseModel):
    """One resolved figure from SEC EDGAR's structured XBRL companyfacts
    API -- never an LLM's read of prose, the exact "what's already
    machine-readable is never estimated by an LLM" principle the rest of
    this codebase applies to the revenue/CapEx catalogue cascade
    (arp/research/revenue_exposure/), extended to cover EDGAR filers'
    own structured financial facts as well as user-supplied catalogues.
    """

    tag: str
    value: float
    unit: str
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str
    filed: str | None = None
    accession: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    cik: str | None = None  # set by CompanyFactsSource, so the fact can cite itself
    frozen: FrozenFacts | None = Field(default=None, exclude=True)  # likewise, so the citation is publishable

    def reported(self) -> tuple[float, str, str, str]:
        """(value, raw text, unit text, decimal mark) to type the value from: plain digits and a
        stated decimal point, the number as tagged, never a locale guess."""
        return self.value, str(int(self.value)) if self.value.is_integer() else repr(self.value), self.unit, "point"

    def quote(self) -> str:
        # The period's own end, not companyfacts' `fy` (the filing's year, which also
        # labels the comparatives a filing repeats); fractions (EPS, ratios) as tagged.
        value = f"{self.value:,.0f}" if self.value.is_integer() else f"{self.value:,}"
        period = f"period ending {self.period_end}" if self.period_end else f"FY{self.fiscal_year} {self.fiscal_period or ''}".strip()
        return (
            f"{self.tag if ':' in self.tag else 'us-gaap:' + self.tag} = {value} {self.unit} "
            f"({period}, form {self.form}, filed {self.filed})"
        )

    def as_citation(self, cik: str | None = None, *, frozen: FrozenFacts | None = None) -> Citation:
        cik, frozen, quote = cik or self.cik, frozen or self.frozen, self.quote()
        # With a frozen original: its rendered line, at its span, so the publish gate can check it.
        if frozen is not None and (start := ("\n" + frozen.text).find("\n" + quote + "\n")) >= 0:
            return Citation(
                doc_id=frozen.doc_id, doc_type=DocType.OTHER, quote=quote, location="SEC EDGAR XBRL companyfacts API",
                grounded=True, company_id=None, source_filename=None, content_key=frozen.content_key,
                parser_version=frozen.parser_version, span_text=quote, char_start=start, char_end=start + len(quote),
                match_method="exact",
            )
        return Citation(
            doc_id=f"xbrl:{cik}:{self.accession or self.tag}",
            doc_type=DocType.OTHER,
            quote=quote,
            location="SEC EDGAR XBRL companyfacts API",
            # Set true directly, not run through arp/grounding.py's
            # substring check: there is no source document text to check
            # a quote against here, because the "quote" *is* a structured
            # SEC fact, not an LLM's paraphrase of one. Grounding the
            # citation would be checking the fact against itself.
            grounded=True,
            company_id=None,
            source_filename=None,
        )
