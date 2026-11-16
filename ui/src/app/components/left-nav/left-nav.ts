import { Component, inject } from '@angular/core';
import { MatListModule } from '@angular/material/list';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { formBadge } from '../../world/kind-families';
import { kindIconPath, kindInitial } from '../../world/kind-icon';
import { WorldProjectService } from '../../world/world-project.service';

/** Every word in the sidebar that belongs to the world section. */
const WORDS = {
  world: 'World',
  projects: 'Projects',
  statistics: 'Statistics',
  sources: 'Sources',
  vocabulary: 'Vocabulary',
  story: 'Story graph',
  noProject: 'No project yet.',
  kindsBroken: 'This project\'s kinds could not be read.',
  count: (n: number) => `${n} in this project`,
};

@Component({
  imports: [RouterLink, RouterLinkActive, MatListModule],
  selector: 'app-left-nav',
  styleUrl: './left-nav.scss',
  templateUrl: './left-nav.html',
})
export class LeftNav {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  readonly iconPath = kindIconPath;
  readonly initial = kindInitial;
  readonly badge = formBadge;
}
