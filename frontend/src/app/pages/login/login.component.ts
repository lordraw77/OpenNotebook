import { Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { Router } from '@angular/router';

import { errorMessage } from '../../core/api.service';
import { AdminApi, AuthConfig } from '../../core/admin.api';
import { AuthService } from '../../core/auth.service';
import { TranslatePipe, t } from '../../core/i18n';

@Component({
  selector: 'app-login',
  imports: [
    TranslatePipe,
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
  ],
  template: `
    <div class="wrap">
      <mat-card appearance="outlined" class="card">
        <mat-card-header>
          <mat-card-title class="title"
            ><span class="logo"><mat-icon>auto_stories</mat-icon></span>
            <span class="gradient-text">OpenNotebook</span></mat-card-title
          >
          <mat-card-subtitle>{{ 'Sign in to continue' | t }}</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          @if (error()) {
            <p class="error-text" role="alert">{{ error() }}</p>
          }
          @if (config()?.oidc) {
            <a mat-flat-button class="sso" href="/api/auth/oidc/login?next=/workbench">
              <mat-icon>key</mat-icon> {{ config()!.oidc_label }}
            </a>
            @if (config()!.password) {
              <div class="or">
                <span>{{ 'or' | t }}</span>
              </div>
            }
          }
          @if (config() === null || config()!.password) {
            <form (ngSubmit)="submit()" class="form">
              <mat-form-field appearance="outline">
                <mat-label>{{ 'Email' | t }}</mat-label>
                <input
                  matInput
                  type="email"
                  name="email"
                  [(ngModel)]="email"
                  autocomplete="username"
                  required
                />
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>{{ 'Password' | t }}</mat-label>
                <input
                  matInput
                  type="password"
                  name="password"
                  [(ngModel)]="password"
                  autocomplete="current-password"
                  required
                />
              </mat-form-field>
              <button mat-flat-button type="submit" [disabled]="busy() || !email || !password">
                {{ 'Sign in' | t }}
              </button>
            </form>
          }
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: `
    .wrap {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 16px;
      box-sizing: border-box;
    }
    .card {
      width: min(400px, 100%);
      border-top: 3px solid transparent;
      border-image: var(--on-gradient) 1;
      border-image-slice: 1 0 0 0;
      box-shadow: 0 12px 40px var(--on-glow);
    }
    .logo {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      border-radius: 10px;
      background: var(--on-gradient);
      color: #fff;
    }
    .title {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
    }
    .sso {
      width: 100%;
      margin-top: 16px;
    }
    .or {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 16px 0 0;
      color: var(--mat-sys-on-surface-variant);
      font-size: 12px;
    }
    .or::before,
    .or::after {
      content: '';
      flex: 1;
      border-top: 1px solid var(--mat-sys-outline-variant);
    }
    .form {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-top: 16px;
    }
  `,
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly admin = inject(AdminApi);
  /** Message from a failed single sign-on (?error=...). */
  readonly errorParam = input<string | undefined>(undefined, { alias: 'error' });
  readonly config = signal<AuthConfig | null>(null);

  constructor() {
    this.admin
      .authConfig()
      .then((c) => this.config.set(c))
      .catch(() => this.config.set({ password: true, oidc: false, oidc_label: '' }));
    effect(() => {
      const message = this.errorParam();
      if (message) this.error.set(message);
    });
  }

  email = '';
  password = '';
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  async submit(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.login(this.email, this.password);
      await this.router.navigateByUrl('/workbench');
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }
}
