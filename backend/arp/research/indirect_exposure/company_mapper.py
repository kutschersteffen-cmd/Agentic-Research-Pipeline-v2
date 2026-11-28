from __future__ import annotations

from pydantic import BaseModel

from arp.core.nace import code_set_sectors, isic_to_nace2, nace_sectors
from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.common import CompanyRef

_SYSTEM_PROMPT = """\
You classify a company into the single best-fitting sector from a fixed, \
closed list of EXIOBASE sectors. Answer with the sector name exactly as \
listed. If none of the listed sectors is a good fit for the company's \
actual business, return null rather than forcing the closest-sounding option."""


class _CompanySectorClassification(BaseModel):
    sector: str | None
    rationale: str


def company_nace(company: CompanyRef) -> tuple[str, str, str] | None:
    """(scheme, code, rev) the `nace` source links by: the NACE code, else a 4-digit ISIC Rev. 4 class the UN
    table maps, else a 2-digit ISIC Rev. 4 division (read as the NACE Rev. 2 division) that maps to a sector."""
    if company.nace_code:
        return ("nace21" if company.nace_rev == "2.1" else "nace2"), company.nace_code, company.nace_rev
    isic = company.isic_code or ""
    if isic.isdigit() and (len(isic) == 2 and nace_sectors(isic, "2") or len(isic) == 4 and isic_to_nace2(isic)):
        return "isic4", isic, "2"
    return None


def company_nace_sectors(company: CompanyRef) -> set[str]:
    """The sector names of the company's NACE set; empty when company_nace gives none."""
    found = company_nace(company)
    if found is None:
        return set()
    return code_set_sectors(*found)


async def resolve_company_sector(
    company: CompanyRef, model: LeontiefModel, llm: LLMClient
) -> tuple[str | None, LLMUsage]:
    """The company's EXIOBASE sector when its NACE/ISIC codes don't give one.

    A company `company_nace` resolves (a NACE code, or a 2- or 4-digit ISIC
    Rev.4 code) gets None with no LLM call: its sectors come from that code.
    Otherwise one LLM call picks a sector name from the model's closed list
    (the shared disk cache makes reruns free); an answer not in the list
    gives None.
    """
    if company_nace(company) is not None:
        return None, LLMUsage()

    prompt = (
        f"Company: {company.name}\n"
        f"Sector (if known): {company.sector or 'unknown'}\n"
        f"Country: {company.country or 'unknown'}\n\n"
        f"Available EXIOBASE sectors:\n{model.industry_prompt_list()}"
    )
    draft, usage = await llm.complete_structured(
        system=_SYSTEM_PROMPT, prompt=prompt, output_model=_CompanySectorClassification
    )
    return (draft.sector if draft.sector in model.codes else None), usage
