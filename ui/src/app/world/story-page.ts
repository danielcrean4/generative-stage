import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom, map } from 'rxjs';
import { EDGE_WORDS, around, entityOptions, nodeName, problemCount, short, withStory } from './story-model';
import { NODE_HEIGHT, NODE_WIDTH, layout } from './story-layout';
import { WorldApi } from './world-api';
import { WorldGate } from './world-gate';
import { StoryEdge, StoryEdgeKind, StoryGraph } from './world-models';
import { WorldProjectService } from './world-project.service';

const WORDS = {
  title: 'Story graph',
  intro: 'How the project\'s story fits together: steps, lines and replies, what each rule checks and what it changes. Read from the entities and the marks in their kinds; nothing here is edited.',
  loading: 'Loading…',
  entity: 'Show',
  all: 'All entities',
  allEntities: 'Include entities with no story',
  graph: 'Graph',
  list: 'List',
  empty: 'Nothing to show. A kind takes part when its schema marks story nodes (x-story) or conditions and effects (x-vocabulary).',
  pick: 'Pick a node to see its words, conditions and effects.',
  profile: 'Open profile',
  focus: 'Show its story',
  back: 'Back to all entities',
  conditions: 'Conditions',
  effects: 'Effects',
  leadsTo: 'Leads to',
  comesFrom: 'Comes from',
  reads: 'Reads',
  shorthand: 'Older shorthand: the game turns it into a condition, so what it reads is not known here.',
  ends: 'ends here',
  hidden: (n: number) => `${n} more without a story`,
  legend: 'Edges',
  count: (n: number) => (n > 1 ? ` ×${n}` : ''),
  problems: (n: number) => `${n} problem${n === 1 ? '' : 's'}`,
  inner: (n: number) => `${n} story node${n === 1 ? '' : 's'}`,
};
const NARROW = '(max-width: 600px)';
const LABEL_LIMIT = 26;
const TEXT_LIMIT = 30;

/** The project's story graph, read-only: all entities, or one in full, as a drawing or a list. */
@Component({
  selector: 'app-story-page',
  imports: [WorldGate, RouterLink],
  styleUrls: ['./world-pages.scss', './story-page.scss'],
  templateUrl: './story-page.html',
})
export class StoryPage {
  readonly w = WORDS;
  readonly edgeWords = EDGE_WORDS;
  readonly edgeKinds = Object.keys(EDGE_WORDS) as StoryEdgeKind[];
  readonly nodeWidth = NODE_WIDTH;
  readonly nodeHeight = NODE_HEIGHT;
  readonly short = short;
  readonly labelLimit = LABEL_LIMIT;
  readonly textLimit = TEXT_LIMIT;
  readonly nodeName = nodeName;
  readonly problemCount = problemCount;
  private readonly api = inject(WorldApi);
  private readonly world = inject(WorldProjectService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly entity = toSignal(this.route.queryParamMap.pipe(map((q) => q.get('entity'))), { initialValue: null });
  readonly status = signal<'loading' | 'ready'>('loading');
  readonly error = signal<string | null>(null);
  readonly overview = signal<StoryGraph | null>(null);
  readonly focus = signal<StoryGraph | null>(null);
  readonly showAll = signal(false);
  readonly mode = signal<'graph' | 'list'>(typeof matchMedia === 'function' && matchMedia(NARROW).matches ? 'list' : 'graph');
  readonly selected = signal<string | null>(null);
  private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');
  private overviewOf: string | null = null; // the project the overview was read for

  readonly options = computed(() => {
    const o = this.overview();
    return o ? entityOptions(o, (k) => this.world.kind(k)?.label ?? k) : [];
  });
  readonly shown = computed(() => {
    if (this.entity()) return this.focus();
    const o = this.overview();
    return o ? withStory(o, this.showAll()) : null;
  });
  readonly hidden = computed(() => (this.entity() ? 0 : (this.overview()?.nodes.length ?? 0) - (this.shown()?.nodes.length ?? 0)));
  readonly nodes = computed(() => new Map((this.shown()?.nodes ?? []).map((n) => [n.id, n])));
  readonly drawing = computed(() => {
    const g = this.shown();
    return g ? layout(g) : null;
  });
  readonly placed = computed(() => {
    const d = this.drawing();
    return d ? d.nodes.map((p) => ({ ...p, node: this.nodes().get(p.id)! })) : [];
  });
  readonly lines = computed(() => {
    const kinds = new Map((this.shown()?.edges ?? []).map((e) => [e.id, e.kind]));
    return (this.drawing()?.edges ?? []).map((e) => ({ ...e, kind: kinds.get(e.id) }));
  });
  /** The list: nodes in the drawing's order (layer by layer), each with the edges leaving it. */
  readonly rows = computed(() => {
    const g = this.shown();
    if (!g) return [];
    const placed = [...(this.drawing()?.nodes ?? [])].sort((a, b) => a.layer - b.layer || a.y - b.y);
    return placed.map((p) => ({ node: this.nodes().get(p.id)!, out: around(g, p.id).out }));
  });
  readonly chosen = computed(() => {
    const id = this.selected();
    const g = this.shown();
    const node = id ? this.nodes().get(id) : undefined;
    return node && g ? { node, ...around(g, node.id) } : null;
  });

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      if (slug && this.world.catalogStatus() === 'ready') void this.load(slug, this.entity());
    });
  }

  kindLabel(kind: string): string {
    return this.world.kind(kind)?.label ?? kind;
  }

  name(id: string | null): string {
    if (!id) return this.w.ends;
    const node = this.nodes().get(id);
    return node ? nodeName(node) : id;
  }

  edgeText(edge: StoryEdge): string {
    return edge.text || edge.label || this.edgeWords[edge.kind];
  }

  select(id: string): void {
    this.selected.set(this.selected() === id ? null : id);
    if (this.selected() && typeof matchMedia === 'function' && matchMedia(NARROW).matches) {
      // On a phone the panel sits below the list; bring it into view.
      setTimeout(() => this.panel()?.nativeElement.scrollIntoView({ block: 'start' }));
    }
  }

  show(entity: string | null): void {
    this.selected.set(entity);
    void this.router.navigate([], { queryParams: { entity: entity || null } });
  }

  private async load(slug: string, entity: string | null): Promise<void> {
    this.status.set('loading');
    this.error.set(null);
    try {
      if (this.overviewOf !== slug) {
        this.overview.set(await firstValueFrom(this.api.story(slug)));
        this.overviewOf = slug;
      }
      this.focus.set(entity ? await firstValueFrom(this.api.story(slug, entity)) : null);
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : String(err));
    }
    this.status.set('ready');
  }
}
