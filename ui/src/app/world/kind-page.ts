import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { FieldType, FormField, buildFields } from './schema-form';
import { Kind, LinkType } from './world-models';
import { WorldProjectService } from './world-project.service';
import { WorldGate } from './world-gate';

/** Every word on this screen. */
const WORDS = {
  back: 'Back to the list',
  notFound: 'This project has no kind with that name.',
  about: 'A kind is a type of thing in your world. Its fields below come from its schema file in the project folder; edit that file to change them.',
  factsTitle: 'Names',
  titleField: 'Title field',
  briefField: 'Brief field',
  tagsField: 'Tags field',
  noTags: 'none (this kind has no tags)',
  noBrief: 'none (this kind has no short description)',
  icon: 'Icon',
  fieldsTitle: 'Fields',
  colName: 'Field',
  colType: 'Kind of value',
  colRequired: 'Required',
  colNotes: 'Notes',
  yes: 'yes',
  no: 'no',
  linksTitle: 'Links',
  noLinks: 'No link types are declared for this kind.',
  outgoing: (label: string, targets: string) => `${label} → ${targets}`,
  incoming: (label: string, sources: string) => `${label} ← ${sources}`,
  types: {
    string: 'single line of text',
    text: 'long text',
    number: 'number',
    integer: 'whole number',
    boolean: 'yes or no',
    enum: 'one of a list',
    tags: 'tags',
    group: 'group of fields',
    unsupported: 'other (shown read-only)',
  } satisfies Record<FieldType, string>,
  oneOf: 'one of: ',
  maxLength: (n: number) => `up to ${n} characters`,
};

interface Row {
  field: FormField;
  depth: number;
  notes: string;
}

@Component({
  selector: 'app-kind-page',
  imports: [RouterLink, WorldGate],
  styleUrl: './world-pages.scss',
  template: `
    <app-world-gate>
      @if (kind(); as k) {
        <section class="world-page" data-page="kind">
          <header class="page-head">
            <h2>{{ k.label }}</h2>
            <span class="spacer"></span>
            <a [routerLink]="['/world', k.id]">{{ w.back }}</a>
          </header>
          <p class="intro">{{ w.about }}</p>

          <h3>{{ w.factsTitle }}</h3>
          <dl class="facts">
            <dt>{{ w.titleField }}</dt><dd>{{ k.title_field }}</dd>
            <dt>{{ w.briefField }}</dt><dd>{{ k.brief_field ?? w.noBrief }}</dd>
            <dt>{{ w.tagsField }}</dt><dd>{{ k.tags_field ?? w.noTags }}</dd>
            <dt>{{ w.icon }}</dt><dd>{{ k.icon }}</dd>
          </dl>

          <h3>{{ w.fieldsTitle }}</h3>
          <table class="schema-table">
            <thead>
              <tr><th>{{ w.colName }}</th><th>{{ w.colType }}</th><th>{{ w.colRequired }}</th><th>{{ w.colNotes }}</th></tr>
            </thead>
            <tbody>
              @for (row of rows(); track row.field.pointer) {
                <tr [attr.data-field]="row.field.pointer">
                  <td [style.padding-left.rem]="0.5 + row.depth * 1.25">{{ row.field.label }}</td>
                  <td>{{ w.types[row.field.type] }}</td>
                  <td>{{ row.field.required ? w.yes : w.no }}</td>
                  <td>{{ row.notes }}</td>
                </tr>
              }
            </tbody>
          </table>

          <h3>{{ w.linksTitle }}</h3>
          @if (linkLines().length === 0) {
            <p class="muted">{{ w.noLinks }}</p>
          } @else {
            <ul class="link-lines">
              @for (line of linkLines(); track line) {
                <li>{{ line }}</li>
              }
            </ul>
          }
        </section>
      } @else {
        <p class="error" role="alert">{{ w.notFound }}</p>
      }
    </app-world-gate>
  `,
  styles: `
    .facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1.5rem; margin: 0; }
    .facts dt { color: var(--mat-sys-on-surface-variant); }
    .facts dd { margin: 0; }
    .schema-table { border-collapse: collapse; max-width: 52rem; width: 100%; }
    .schema-table th, .schema-table td { text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--mat-sys-outline-variant); vertical-align: top; }
    .link-lines { margin: 0; padding-left: 1.25rem; }
    h3 { margin: 0.75rem 0 0.25rem; }
  `,
})
export class KindPage {
  readonly w = WORDS;
  private readonly world = inject(WorldProjectService);
  private readonly route = inject(ActivatedRoute);
  private readonly kindId = toSignal(this.route.paramMap.pipe(map((p) => p.get('kind'))), { initialValue: null });

  readonly kind = computed<Kind | null>(() => this.world.kind(this.kindId()));

  readonly rows = computed<Row[]>(() => {
    const k = this.kind();
    if (!k) return [];
    const out: Row[] = [];
    const walk = (fields: FormField[], depth: number) => {
      for (const field of fields) {
        out.push({ field, depth, notes: this.notes(field) });
        walk(field.children, depth + 1);
      }
    };
    walk(buildFields(k.schema, { briefField: k.brief_field }), 0);
    return out;
  });

  readonly linkLines = computed<string[]>(() => {
    const k = this.kind();
    if (!k) return [];
    const names = (ids: string[]) => ids.map((id) => this.world.kind(id)?.plural_label ?? id).join(', ');
    const lines: string[] = [];
    this.world.linkTypes().forEach((t: LinkType) => {
      if (t.source_kinds.includes(k.id)) lines.push(WORDS.outgoing(t.label, names(t.target_kinds)));
      if (t.target_kinds.includes(k.id)) lines.push(WORDS.incoming(t.inverse_label, names(t.source_kinds)));
    });
    return lines;
  });

  private notes(field: FormField): string {
    const parts: string[] = [];
    if (field.type === 'enum') parts.push(WORDS.oneOf + field.enumValues.join(', '));
    if (field.maxLength) parts.push(WORDS.maxLength(field.maxLength));
    if (field.description) parts.push(field.description);
    return parts.join('. ');
  }
}
