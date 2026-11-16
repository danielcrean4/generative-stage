import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { WorldProjectService } from './world-project.service';

const WORDS = {
  loading: 'Loading…',
  noProject: 'There is no current project.',
  choose: 'Choose or make a project',
  broken: 'This project\'s kinds could not be read:',
  unreachable: 'The world model could not be reached:',
};

/**
 * Wraps a world screen with the states every one of them shares: no current project, the project
 * still loading, and a project whose kinds are broken (the API's message is shown word for word).
 * The screen's own content shows only when the project is ready.
 */
@Component({
  selector: 'app-world-gate',
  imports: [RouterLink],
  styles: '.gate { padding: 1rem 0; } .error { color: var(--mat-sys-error); } .muted { opacity: 0.7; }',
  template: `
    @if (world.listStatus() === 'loading' || world.catalogStatus() === 'loading') {
      <p class="muted gate" data-gate="loading">{{ w.loading }}</p>
    } @else if (world.listError(); as e) {
      <p class="error gate" role="alert" data-gate="unreachable">{{ w.unreachable }} {{ e.message }}</p>
    } @else if (!world.slug()) {
      <p class="gate" data-gate="no-project">
        {{ w.noProject }} <a routerLink="/projects">{{ w.choose }}</a>.
      </p>
    } @else if (world.catalogError(); as e) {
      <p class="error gate" role="alert" data-gate="broken">{{ w.broken }} {{ e.message }}</p>
    } @else {
      <ng-content />
    }
  `,
})
export class WorldGate {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
}
