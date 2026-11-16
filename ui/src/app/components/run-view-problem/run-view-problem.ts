import { Component, computed, input } from '@angular/core';
import { RUN_VIEW_START_COMMAND, describeRunViewError } from '../../run-view-api';

/** Error state shared by every page that reads from the read-only server (runs and docs); shows how to start the server when it is down. */
@Component({
  selector: 'app-run-view-problem',
  template: `
    <div class="problem" role="alert">
      <p class="message">{{ info().message }}</p>
      @if (info().serverDown) {
        <p>
          Start it from the <code>server/</code> folder:
          <code class="command">{{ startCommand }}</code>
        </p>
      }
    </div>
  `,
  styles: `
    .problem {
      border: 1px solid var(--mat-sys-error);
      border-radius: 8px;
      padding: 0.5rem 1rem;
      color: var(--mat-sys-error);
    }
    .command {
      display: block;
      margin-top: 0.25rem;
      color: var(--mat-sys-on-surface);
      overflow-wrap: anywhere;
    }
  `,
})
export class RunViewProblem {
  readonly error = input.required<unknown>();
  readonly startCommand = RUN_VIEW_START_COMMAND;
  readonly info = computed(() => describeRunViewError(this.error()));
}
