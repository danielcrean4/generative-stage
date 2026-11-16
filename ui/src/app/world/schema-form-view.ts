import { NgTemplateOutlet } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipInputEvent, MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { FormField, getValue, parseNumber } from './schema-form';
import { JsonObject } from './world-models';

/** Every word this form shows itself; the labels of fields come from the kind's schema. */
const WORDS = {
  addTag: 'Add a tag, then press Enter',
  removeTag: 'Remove tag',
  none: 'Not set',
  unsupported: 'This field cannot be edited here. It is kept as it is when you save.',
};

export interface FieldChange {
  path: string[];
  value: unknown;
}

/**
 * Draws the fields that `buildFields` describes, for any kind. It holds no state of its own:
 * values come in, edits go out as `valueChange`, and error messages arrive keyed by field pointer.
 */
@Component({
  selector: 'app-schema-form',
  imports: [NgTemplateOutlet, MatFormFieldModule, MatInputModule, MatCheckboxModule, MatChipsModule],
  styleUrl: './schema-form-view.scss',
  templateUrl: './schema-form-view.html',
})
export class SchemaFormView {
  readonly w = WORDS;
  readonly fields = input.required<FormField[]>();
  readonly values = input.required<JsonObject>();
  readonly errors = input<Record<string, string>>({});
  readonly readonly = input(false);
  readonly valueChange = output<FieldChange>();

  get(field: FormField): unknown {
    return getValue(this.values(), field.path);
  }

  text(field: FormField): string {
    const v = this.get(field);
    return v === undefined || v === null ? '' : String(v);
  }

  tags(field: FormField): string[] {
    const v = this.get(field);
    return Array.isArray(v) ? (v as string[]) : [];
  }

  json(field: FormField): string {
    const v = this.get(field);
    return v === undefined ? this.w.none : JSON.stringify(v, null, 2);
  }

  setText(field: FormField, event: Event): void {
    const value = (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
    if (field.type === 'enum') {
      const match = field.enumValues.find((v) => String(v) === value);
      this.emit(field, value === '' ? undefined : (match ?? value));
    } else if (field.type === 'number' || field.type === 'integer') {
      this.emit(field, parseNumber(value, field.type === 'integer'));
    } else {
      this.emit(field, value);
    }
  }

  setBoolean(field: FormField, checked: boolean): void {
    this.emit(field, checked);
  }

  addTag(field: FormField, event: MatChipInputEvent): void {
    const value = event.value.trim();
    if (value && !this.tags(field).includes(value)) {
      this.emit(field, [...this.tags(field), value]);
    }
    event.chipInput.clear();
  }

  removeTag(field: FormField, tag: string): void {
    this.emit(field, this.tags(field).filter((t) => t !== tag));
  }

  private emit(field: FormField, value: unknown): void {
    this.valueChange.emit({ path: field.path, value });
  }
}
