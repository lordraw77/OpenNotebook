import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatListModule } from '@angular/material/list';
import { MatSelectModule } from '@angular/material/select';

import { Grant, GrantRole, TreeNodeDto, User } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';

export interface NameDialogData {
  title: string;
  label: string;
  value?: string;
}

@Component({
  selector: 'app-name-dialog',
  imports: [FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <form (ngSubmit)="ok()">
      <mat-dialog-content>
        <mat-form-field appearance="outline" class="full">
          <mat-label>{{ data.label }}</mat-label>
          <input
            matInput
            name="value"
            [(ngModel)]="value"
            maxlength="200"
            required
            cdkFocusInitial
          />
        </mat-form-field>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancel</button>
        <button mat-flat-button type="submit" [disabled]="!value.trim()">Save</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: '.full { width: 100%; min-width: min(360px, 70vw); }',
})
export class NameDialogComponent {
  protected readonly data = inject<NameDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<NameDialogComponent, string>);
  value = this.data.value ?? '';

  ok(): void {
    if (this.value.trim()) this.ref.close(this.value.trim());
  }
}

type DirectoryUser = Pick<User, 'id' | 'email' | 'display_name'>;

@Component({
  selector: 'app-share-dialog',
  imports: [
    FormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatSelectModule,
    MatListModule,
    MatIconModule,
    MatAutocompleteModule,
  ],
  template: `
    <h2 mat-dialog-title>Share “{{ node.name }}”</h2>
    <mat-dialog-content>
      <p class="muted">
        Access granted here also applies to everything inside this {{ node.kind }}.
      </p>
      <mat-list>
        @for (g of grants(); track g.principal_type + g.principal_id) {
          <mat-list-item>
            <mat-icon matListItemIcon>{{
              g.principal_type === 'group' ? 'group' : 'person'
            }}</mat-icon>
            <span matListItemTitle>{{ g.principal_name ?? g.principal_id }}</span>
            <span matListItemLine>{{ g.role }}</span>
            <button mat-icon-button matListItemMeta aria-label="Remove access" (click)="remove(g)">
              <mat-icon>close</mat-icon>
            </button>
          </mat-list-item>
        } @empty {
          <p class="muted">No direct grants on this node.</p>
        }
      </mat-list>
      <div class="row add">
        <mat-form-field appearance="outline" class="grow">
          <mat-label>User</mat-label>
          <input
            matInput
            [(ngModel)]="query"
            (ngModelChange)="search($event)"
            [matAutocomplete]="auto"
          />
          <mat-autocomplete
            #auto="matAutocomplete"
            [displayWith]="display"
            (optionSelected)="picked = $event.option.value"
          >
            @for (u of candidates(); track u.id) {
              <mat-option [value]="u">{{ u.display_name }} · {{ u.email }}</mat-option>
            }
          </mat-autocomplete>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Role</mat-label>
          <mat-select [(ngModel)]="role">
            <mat-option value="viewer">Viewer</mat-option>
            <mat-option value="editor">Editor</mat-option>
            <mat-option value="owner">Owner</mat-option>
          </mat-select>
        </mat-form-field>
        <button mat-flat-button (click)="add()" [disabled]="!picked">Add</button>
      </div>
      @if (error()) {
        <p class="error-text">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end"
      ><button mat-button mat-dialog-close>Close</button></mat-dialog-actions
    >
  `,
  styles: '.add { align-items: baseline; } .grow { flex: 1; min-width: 200px; }',
})
export class ShareDialogComponent {
  protected readonly node = inject<TreeNodeDto>(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);

  readonly grants = signal<Grant[]>([]);
  readonly candidates = signal<DirectoryUser[]>([]);
  readonly error = signal<string | null>(null);
  query: string | DirectoryUser = '';
  picked: DirectoryUser | null = null;
  role: GrantRole = 'viewer';

  constructor() {
    void this.load();
  }

  display = (u: DirectoryUser | string | null) => (typeof u === 'string' ? u : (u?.email ?? ''));

  async load(): Promise<void> {
    this.grants.set(await this.api.grants(this.node.id));
  }

  async search(q: string | DirectoryUser): Promise<void> {
    if (typeof q !== 'string') return;
    this.picked = null;
    this.candidates.set(q.length >= 1 ? await this.api.userDirectory(q) : []);
  }

  async add(): Promise<void> {
    if (!this.picked) return;
    this.error.set(null);
    try {
      await this.api.putGrant(this.node.id, {
        principal_type: 'user',
        principal_id: this.picked.id,
        role: this.role,
      });
      this.query = '';
      this.picked = null;
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  async remove(g: Grant): Promise<void> {
    this.error.set(null);
    try {
      await this.api.deleteGrant(this.node.id, g);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }
}
