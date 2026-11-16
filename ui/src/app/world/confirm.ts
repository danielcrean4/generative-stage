import { Component, Injectable, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** Styles the confirm button as the careful choice. */
  danger?: boolean;
}

@Component({
  selector: 'app-confirm-dialog',
  imports: [MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>
      <p class="confirm-message">{{ data.message }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="false">{{ data.cancelLabel ?? w.cancel }}</button>
      <button mat-flat-button [mat-dialog-close]="true" class="confirm-yes" cdkFocusInitial>{{ data.confirmLabel }}</button>
    </mat-dialog-actions>
  `,
  styles: '.confirm-message { max-width: 28rem; white-space: pre-line; }',
})
export class ConfirmDialog {
  readonly w = { cancel: 'Cancel' };
  readonly data = inject<ConfirmOptions>(MAT_DIALOG_DATA);
}

/** One way to ask "are you sure?"; tests replace it with a stub that answers at once. */
@Injectable({ providedIn: 'root' })
export class ConfirmService {
  private readonly dialog = inject(MatDialog);

  async ask(options: ConfirmOptions): Promise<boolean> {
    const ref = this.dialog.open<ConfirmDialog, ConfirmOptions, boolean>(ConfirmDialog, { data: options, autoFocus: 'first-tabbable' });
    return (await firstValueFrom(ref.afterClosed())) === true;
  }
}
