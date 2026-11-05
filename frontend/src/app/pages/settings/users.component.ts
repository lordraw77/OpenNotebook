import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';

import { User } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-users',
  imports: [
    FormsModule,
    MatTableModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatCheckboxModule,
    MatSlideToggleModule,
    MatIconModule,
  ],
  template: `
    <h2 class="section">Users</h2>
    <p class="muted">
      Access to projects, workspaces and notebooks is granted from the Workbench tree (node menu →
      Share).
    </p>
    <mat-card appearance="outlined">
      <mat-card-content>
        <form class="form" (ngSubmit)="create()">
          <mat-form-field appearance="outline">
            <mat-label>Email</mat-label>
            <input matInput type="email" name="email" [(ngModel)]="draft.email" required />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Display name</mat-label>
            <input matInput name="display_name" [(ngModel)]="draft.display_name" required />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Initial password</mat-label>
            <input
              matInput
              type="password"
              name="password"
              [(ngModel)]="draft.password"
              minlength="12"
              autocomplete="new-password"
              required
            />
            <mat-hint>at least 12 characters</mat-hint>
          </mat-form-field>
          <mat-checkbox name="is_admin" [(ngModel)]="draft.is_admin">Administrator</mat-checkbox>
          <button
            mat-flat-button
            type="submit"
            [disabled]="!draft.email || !draft.display_name || draft.password.length < 12"
          >
            <mat-icon>person_add</mat-icon> Create user
          </button>
        </form>
      </mat-card-content>
    </mat-card>

    <div class="table-wrap">
      <table mat-table [dataSource]="users()">
        <ng-container matColumnDef="email">
          <th mat-header-cell *matHeaderCellDef>Email</th>
          <td mat-cell *matCellDef="let u">{{ u.email }}</td>
        </ng-container>
        <ng-container matColumnDef="name">
          <th mat-header-cell *matHeaderCellDef>Name</th>
          <td mat-cell *matCellDef="let u">{{ u.display_name }}</td>
        </ng-container>
        <ng-container matColumnDef="admin">
          <th mat-header-cell *matHeaderCellDef>Admin</th>
          <td mat-cell *matCellDef="let u">
            <mat-slide-toggle
              [checked]="u.is_admin"
              [disabled]="u.id === me()"
              (change)="update(u, { is_admin: $event.checked })"
              aria-label="Administrator"
            ></mat-slide-toggle>
          </td>
        </ng-container>
        <ng-container matColumnDef="active">
          <th mat-header-cell *matHeaderCellDef>Active</th>
          <td mat-cell *matCellDef="let u">
            <mat-slide-toggle
              [checked]="u.is_active"
              [disabled]="u.id === me()"
              (change)="update(u, { is_active: $event.checked })"
              aria-label="Active"
            ></mat-slide-toggle>
          </td>
        </ng-container>
        <tr mat-header-row *matHeaderRowDef="columns"></tr>
        <tr mat-row *matRowDef="let u; columns: columns"></tr>
      </table>
    </div>
  `,
  styles: `
    .section {
      font: var(--mat-sys-title-medium);
      margin: 24px 0 8px;
    }
    .form {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: baseline;
    }
    .form mat-form-field {
      width: min(260px, 100%);
    }
    .table-wrap {
      overflow-x: auto;
      margin-top: 16px;
    }
    table {
      width: 100%;
    }
  `,
})
export class UsersComponent {
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);

  readonly users = signal<User[]>([]);
  readonly me = () => this.auth.user()?.id;
  readonly columns = ['email', 'name', 'admin', 'active'];
  draft = { email: '', display_name: '', password: '', is_admin: false };

  constructor() {
    void this.load();
  }

  async load(): Promise<void> {
    this.users.set(await this.api.users());
  }

  async create(): Promise<void> {
    try {
      await this.api.createUser(this.draft);
      this.draft = { email: '', display_name: '', password: '', is_admin: false };
      this.snack.open('User created', 'Close', { duration: 3000 });
      await this.load();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }

  async update(u: User, body: Partial<Pick<User, 'is_admin' | 'is_active'>>): Promise<void> {
    try {
      await this.api.updateUser(u.id, body);
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
    await this.load();
  }
}
