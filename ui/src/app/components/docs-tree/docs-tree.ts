import { NgTemplateOutlet } from '@angular/common';
import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DocTreeDir } from '../../docs-view-api';
import { countDocFiles } from '../../docs-tree';

/**
 * The docs of one project as nested folders. Folders are native disclosure widgets and files are
 * links, so Tab, Enter and Space work with no extra key handling.
 */
@Component({
  imports: [NgTemplateOutlet, RouterLink],
  selector: 'app-docs-tree',
  styleUrl: './docs-tree.scss',
  templateUrl: './docs-tree.html',
})
export class DocsTree {
  readonly project = input.required<string>();
  readonly root = input.required<DocTreeDir>();
  /** Folders at this depth or shallower start open. */
  readonly openDepth = input(2);

  readonly countFiles = countDocFiles;
}
