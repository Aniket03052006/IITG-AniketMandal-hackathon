/** What KIND of statement a brief sentence is, in words. Never colour alone. */
export const STATEMENT_KIND: Record<string, string> = {
  SOURCE_EVENT: "Source report",
  EVENTSHOCK_ASSESSMENT: "EventShock assessment",
  EXTERNAL_MARKET_OBSERVATION: "External market observation",
  SCENARIO_ASSUMPTION: "Scenario assumption",
  HISTORICAL_OBSERVATION: "Historical observation",
  REALISED_OUTCOME: "Realised outcome",
  PRODUCT_RULE: "Product rule",
};

export const BRIEF_KEY = "brief";

/** The slug of a section id, for an anchor: EXECUTIVE_SUMMARY → executive-summary. */
export const sectionAnchor = (id: string) => `brief-${id.toLowerCase().replaceAll("_", "-")}`;
