import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AdminApi, GroupDto, MemberDto } from '../../core/admin.api';
import { ApiService, errorMessage } from '../../core/api.service';
import { TranslatePipe, t } from '../../core/i18n';

/** Groups (administrators): share nodes with a group instead of single users. */
@Component({
  selector: 'app-groups',
  imports: [
    TranslatePipe,
    FormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatTooltipModule,
  ],
  template: `
    <p class="muted">
      {{
        'Share a project, workspace or notebook with a group (Share… in the Workbench): every member gets the role, on that node and everything inside it. Groups marked SSO are kept in sync with the identity provider at each sign-in.'
          | t
      }}
    </p>
    <form class="create" (ngSubmit)="create()">
      <mat-form-field appearance="outline" subscriptSizing="dynamic">
        <mat-label>{{ 'New group' | t }}</mat-label>
        <input matInput name="name" [(ngModel)]="name" maxlength="200" />
      </mat-form-field>
      <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow">
        <mat-label>{{ 'Description' | t }}</mat-label>
        <input matInput name="description" [(ngModel)]="description" maxlength="1000" />
      </mat-form-field>
      <button mat-flat-button type="submit" [disabled]="!name.trim()">
        <mat-icon>group_add</mat-icon> {{ 'Create' | t }}
      </button>
    </form>

    <div class="layout">
      <section class="list">
        @for (g of groups(); track g.id) {
          <button
            type="button"
            class="group"
            [class.selected]="g.id === selected()?.id"
            (click)="open(g)"
          >
            <mat-icon>group</mat-icon>
            <span class="name">
              {{ g.name }}
              @if (g.description) {
                <span class="muted small">{{ g.description }}</span>
              }
            </span>
            @if (g.source === 'oidc') {
              <span class="badge" [matTooltip]="'Synchronized from single sign-on' | t">SSO</span>
            }
            <span class="count" [matTooltip]="'Members' | t">{{ g.members }}</span>
          </button>
        } @empty {
          <p class="muted">{{ 'No groups yet.' | t }}</p>
        }
      </section>

      @if (selected(); as g) {
        <section class="members">
          <header>
            <h2>{{ g.name }}</h2>
            <span class="spacer"></span>
            <button
              mat-icon-button
              [matTooltip]="'Delete group (its grants are removed)' | t"
              [attr.aria-label]="'Delete group' | t"
              (click)="remove(g)"
            >
              <mat-icon>delete</mat-icon>
            </button>
          </header>
          <div class="add">
            <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow">
              <mat-label>{{ 'Add a member' | t }}</mat-label>
              <input
                matInput
                [(ngModel)]="query"
                (ngModelChange)="search($event)"
                [matAutocomplete]="auto"
              />
              <mat-autocomplete
                #auto="matAutocomplete"
                (optionSelected)="addMember($event.option.value)"
              >
                @for (u of candidates(); track u.id) {
                  <mat-option [value]="u">{{ u.display_name }} · {{ u.email }}</mat-option>
                }
              </mat-autocomplete>
            </mat-form-field>
          </div>
          @for (m of members(); track m.id) {
            <div class="member">
              <mat-icon>person</mat-icon>
              <span class="grow"
                >{{ m.display_name }} <span class="muted">· {{ m.email }}</span></span
              >
              <button
                mat-icon-button
                [attr.aria-label]="'Remove member' | t"
                (click)="removeMember(g, m)"
              >
                <mat-icon>close</mat-icon>
              </button>
            </div>
          } @empty {
            <p class="muted">{{ 'No members.' | t }}</p>
          }
        </section>
      }
    </div>
  `,
  styles: `
    .create {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 16px;
    }
    .grow {
      flex: 1;
      min-width: 200px;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(240px, 360px) 1fr;
      gap: 16px;
    }
    .group {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      padding: 8px 10px;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-body-medium);
      text-align: left;
      cursor: pointer;
    }
    .group:hover {
      background: var(--mat-sys-surface-container-high);
    }
    .group.selected {
      background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .name {
      flex: 1;
      display: flex;
      flex-direction: column;
    }
    .small {
      font-size: 12px;
    }
    .badge,
    .count {
      font-size: 11px;
      padding: 1px 8px;
      border-radius: 9px;
      background: var(--mat-sys-surface-container-highest);
    }
    .badge {
      background: var(--mat-sys-tertiary-container);
      color: var(--mat-sys-on-tertiary-container);
    }
    .members {
      padding: 12px 16px;
      border-radius: 14px;
      border: 1px solid var(--mat-sys-outline-variant);
    }
    .members header {
      display: flex;
      align-items: center;
    }
    h2 {
      font: var(--mat-sys-title-medium);
      margin: 0;
    }
    .spacer {
      flex: 1;
    }
    .add {
      margin: 8px 0;
    }
    .member {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    @media (max-width: 800px) {
      .layout {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class GroupsComponent {
  private readonly admin = inject(AdminApi);
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);

  readonly groups = signal<GroupDto[]>([]);
  readonly selected = signal<GroupDto | null>(null);
  readonly members = signal<MemberDto[]>([]);
  readonly candidates = signal<MemberDto[]>([]);
  name = '';
  description = '';
  query = '';

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    this.groups.set(await this.admin.groups());
    const current = this.selected();
    if (current) this.selected.set(this.groups().find((g) => g.id === current.id) ?? null);
  }

  async open(g: GroupDto): Promise<void> {
    this.selected.set(g);
    this.members.set(await this.admin.members(g.id));
  }

  async create(): Promise<void> {
    await this.run(async () => {
      const g = await this.admin.createGroup(this.name.trim(), this.description.trim() || null);
      this.name = '';
      this.description = '';
      await this.load();
      await this.open(g);
    }, t('Group created'));
  }

  async remove(g: GroupDto): Promise<void> {
    if (
      !confirm(
        t('Delete group “{name}”? Access granted to the group is removed.', { name: g.name }),
      )
    )
      return;
    await this.run(async () => {
      await this.admin.deleteGroup(g.id);
      this.selected.set(null);
      await this.load();
    }, t('Group deleted'));
  }

  async search(q: string | MemberDto): Promise<void> {
    if (typeof q !== 'string') return;
    this.candidates.set(q.length ? await this.api.userDirectory(q) : []);
  }

  async addMember(u: MemberDto): Promise<void> {
    const g = this.selected();
    if (!g) return;
    this.query = '';
    await this.run(async () => {
      await this.admin.addMember(g.id, u.id);
      await this.open(g);
      await this.load();
    });
  }

  async removeMember(g: GroupDto, m: MemberDto): Promise<void> {
    await this.run(async () => {
      await this.admin.removeMember(g.id, m.id);
      await this.open(g);
      await this.load();
    });
  }

  private async run(action: () => Promise<void>, ok?: string): Promise<void> {
    try {
      await action();
      if (ok) this.snack.open(ok, t('Close'), { duration: 3000 });
    } catch (err) {
      this.snack.open(errorMessage(err), t('Close'), { duration: 5000 });
    }
  }
}
