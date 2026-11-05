import { Component, computed, inject, signal } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';

import { TreeNodeDto } from '../../core/api.models';
import { ApiService } from '../../core/api.service';
import { breadcrumb, hasRole } from '../workbench/tree';

@Component({
  selector: 'app-upload',
  imports: [MatCardModule, MatFormFieldModule, MatSelectModule, MatIconModule],
  template: `
    <div class="page">
      <h1>Upload sources</h1>
      <mat-form-field appearance="outline" class="target">
        <mat-label>Target notebook</mat-label>
        <mat-select [value]="target()" (valueChange)="target.set($event)">
          @for (n of notebooks(); track n.id) {
            <mat-option [value]="n.id">{{ label(n) }}</mat-option>
          } @empty {
            <mat-option disabled>No notebook where you can upload</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <mat-card appearance="outlined" class="drop" aria-disabled="true">
        <mat-icon>cloud_upload</mat-icon>
        <p>Drag files, archives or images here, or add a URL.</p>
        <p class="muted">
          File ingestion (PDF, TXT, Markdown, DOCX, code, archives, images, web pages) arrives in
          milestone M1–M3.
        </p>
      </mat-card>
    </div>
  `,
  styles: `
    .target {
      width: min(560px, 100%);
    }
    .drop {
      display: grid;
      place-items: center;
      text-align: center;
      padding: 48px 16px;
      border-style: dashed;
    }
    .drop mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: var(--mat-sys-primary);
    }
  `,
})
export class UploadComponent {
  private readonly api = inject(ApiService);
  private readonly all = signal<TreeNodeDto[]>([]);
  readonly notebooks = computed(() =>
    this.all().filter((n) => n.kind === 'notebook' && hasRole(n, 'editor')),
  );
  readonly target = signal<string | null>(null);

  constructor() {
    void this.api.nodes().then((n) => this.all.set(n));
  }

  label(n: TreeNodeDto): string {
    return breadcrumb(this.all(), n.id)
      .map((x) => x.name)
      .join(' / ');
  }
}
