/** The reviewer's name, remembered in this browser only (never sent anywhere but with a decision they record). Storage may be blocked: it then lasts for the page. */
const KEY = "eventshock-analyst";
let memory = "";

export function getAnalyst(): string {
  try {
    return window.localStorage.getItem(KEY) ?? ""; // memory is only for when storage is blocked: a cleared store means no name
  } catch {
    return memory;
  }
}

export function setAnalyst(name: string): void {
  memory = name;
  try {
    window.localStorage.setItem(KEY, name);
  } catch {
    /* blocked storage: keep it in memory */
  }
}
