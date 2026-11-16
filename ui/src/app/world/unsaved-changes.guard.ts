import { CanDeactivateFn } from '@angular/router';

export interface HasUnsavedChanges {
  /** True when leaving would lose edits. */
  hasUnsavedChanges(): boolean;
  /** Ask the person; true means they chose to leave anyway. */
  confirmLeave(): Promise<boolean>;
}

/** Stops a route change away from a page with unsaved edits, until the person says to go ahead. */
export const unsavedChangesGuard: CanDeactivateFn<HasUnsavedChanges> = async (page) =>
  !page.hasUnsavedChanges() || (await page.confirmLeave());
