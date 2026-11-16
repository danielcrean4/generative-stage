import { Component, input, output } from '@angular/core';
import { ParamField, ParamModel, activeFields, setValue, show } from './parametric-model';
import { JsonObject } from './world-models';

/**
 * The form of a parametric kind, made from its parameter model: a slider with a number box for a range, a select for
 * an enum, a checkbox for a switch and a colour picker for a colour. Only the fields that apply to the row are shown.
 * It holds no state: the row comes in and the changed row goes out.
 */
@Component({
  selector: 'app-parametric-form',
  template: `
    <div class="fields" data-form="parametric">
      @for (f of fields(); track f.name) {
        <label class="field" [attr.data-param]="f.name" [attr.title]="f.about || null">
          <span class="name">{{ f.label }}</span>
          @switch (f.type) {
            @case ('enum') {
              <select [value]="row()[f.name]" (change)="change(f, $any($event.target).value)" [disabled]="disabled()">
                @for (v of f.values; track v) {
                  <option [value]="v" [selected]="row()[f.name] === v">{{ v }}</option>
                }
              </select>
            }
            @case ('boolean') {
              <input type="checkbox" [checked]="row()[f.name] === true" (change)="change(f, $any($event.target).checked)" [disabled]="disabled()" />
            }
            @case ('colour') {
              <input type="color" [value]="row()[f.name]" (input)="change(f, $any($event.target).value)" [disabled]="disabled()" />
            }
            @default {
              <input type="range" [min]="f.min" [max]="f.max" [step]="f.step ?? 'any'" [value]="row()[f.name]" (input)="change(f, +$any($event.target).value)" [disabled]="disabled()" />
              <output [attr.data-value]="f.name">{{ shown(f) }}</output>
            }
          }
        </label>
      }
    </div>
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .field select, .field input[type='checkbox'], .field input[type='color'] { justify-self: start; grid-column: 2; }
    .fields { display: grid; gap: 0.6rem; }
    .field { display: grid; grid-template-columns: 7rem minmax(8rem, 1fr) 4.5rem; align-items: center; gap: 0.5rem; }
    .field .name { opacity: 0.8; }
    output { text-align: right; font-variant-numeric: tabular-nums; }
  `,
})
export class ParametricForm {
  readonly model = input.required<ParamModel>();
  readonly row = input.required<JsonObject>();
  readonly disabled = input(false);
  readonly rowChange = output<JsonObject>();

  fields(): ParamField[] {
    return activeFields(this.model(), this.row());
  }

  shown(f: ParamField): string {
    return show(f, this.row()[f.name]);
  }

  change(f: ParamField, value: unknown): void {
    this.rowChange.emit(setValue(this.model(), this.row(), f.name, value));
  }
}
