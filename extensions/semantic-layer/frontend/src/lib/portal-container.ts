import * as React from "react"

// Popups render inside the extension root so they inherit its scoped theme tokens instead of Superset's body.
export const PortalContainerContext = React.createContext<HTMLElement | null>(null)

export function usePortalContainer() {
  return React.useContext(PortalContainerContext) ?? undefined
}
