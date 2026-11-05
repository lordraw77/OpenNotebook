import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { TokenResponse, User } from './api.models';

/**
 * Access token kept in memory only; the refresh token lives in an HttpOnly cookie scoped to /api/auth.
 * A page reload restores the session through POST /api/auth/refresh.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly token = signal<string | null>(null);
  readonly user = signal<User | null>(null);
  readonly isAuthenticated = computed(() => this.user() !== null);
  readonly isAdmin = computed(() => this.user()?.is_admin ?? false);

  private refreshing: Promise<boolean> | null = null;
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;

  accessToken(): string | null {
    return this.token();
  }

  async login(email: string, password: string): Promise<void> {
    const res = await firstValueFrom(
      this.http.post<TokenResponse>(
        '/api/auth/login',
        { email, password },
        { withCredentials: true },
      ),
    );
    this.apply(res);
  }

  /** Single-flight refresh shared by concurrent callers. */
  refresh(): Promise<boolean> {
    this.refreshing ??= firstValueFrom(
      this.http.post<TokenResponse>('/api/auth/refresh', {}, { withCredentials: true }),
    )
      .then((res) => {
        this.apply(res);
        return true;
      })
      .catch(() => {
        this.clear();
        return false;
      })
      .finally(() => (this.refreshing = null));
    return this.refreshing;
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(this.http.post('/api/auth/logout', {}, { withCredentials: true }));
    } finally {
      this.clear();
      await this.router.navigate(['/login']);
    }
  }

  private apply(res: TokenResponse): void {
    this.token.set(res.access_token);
    this.user.set(res.user);
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    // Renew one minute before expiry.
    const delay = Math.max(10, res.expires_in - 60) * 1000;
    this.refreshTimer = setTimeout(() => void this.refresh(), delay);
  }

  private clear(): void {
    this.token.set(null);
    this.user.set(null);
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
  }
}
