import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { RouterLink } from '@angular/router';
import { PRODUCT_NAME } from '../../brand';
import { WorldProjectService } from '../../world/world-project.service';

/** Words for the world project shown in the bar. */
const WORDS = {
  label: 'Project',
  none: 'No project: choose one',
  switch: 'Switch project',
  manage: 'Manage projects…',
};

@Component({
  imports: [MatButtonModule, MatMenuModule, RouterLink],
  selector: 'app-top-nav',
  styleUrl: './top-nav.scss',
  templateUrl: './top-nav.html',
})
export class TopNav {
  readonly w = WORDS;
  readonly brand = PRODUCT_NAME;
  readonly world = inject(WorldProjectService);

  pickWorld(slug: string): void {
    void this.world.select(slug);
  }
}
