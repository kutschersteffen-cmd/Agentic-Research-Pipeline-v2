import { useState } from "react";
import { SimulatedEsg } from "../company/SimulatedEsg";
import { universeRef } from "../company/companyQuery";
import { ProfileActionStrip } from "./ProfileActionStrip";

/** Company Profile: the native issuer action strip and simulated ESG profile card. */
export function CompanyProfiles() {
  const [companyId, setCompanyId] = useState("");

  return (
    <>
      <ProfileActionStrip companyId={companyId} onCompany={setCompanyId} />
      {companyId && <SimulatedEsg key={companyId} companyRef={universeRef(companyId)} showEmpty />}
    </>
  );
}
