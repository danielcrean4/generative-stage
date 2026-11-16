import { BreakpointObserver } from '@angular/cdk/layout';
import { Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { RouterOutlet } from '@angular/router';
import { map } from 'rxjs';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { LeftNav } from './components/left-nav/left-nav';
import { TopNav } from './components/top-nav/top-nav';
import { WorldProjectService } from './world/world-project.service';

@Component({
  imports: [RouterOutlet, LeftNav, TopNav, MatButtonModule, MatSidenavModule, MatToolbarModule],
  selector: 'app-root',
  styleUrl: './app.scss',
  templateUrl: './app.html',
})
export class App {
  private readonly world = inject(WorldProjectService);

  /** On a phone the side navigation would leave the page no room, so it slides over it instead. */
  readonly narrow = toSignal(inject(BreakpointObserver).observe('(max-width: 760px)').pipe(map((state) => state.matches)), { initialValue: false });
  readonly menuOpen = signal(false);

  constructor() {
    void this.world.load();
  }
}
