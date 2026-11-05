import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  Router,
  RouterStateSnapshot,
  UrlTree,
  provideRouter,
} from '@angular/router';

import { AuthService } from './auth.service';
import { authGuard } from './guards';

describe('authGuard', () => {
  const run = (auth: Partial<AuthService>) => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), { provide: AuthService, useValue: auth }],
    });
    return TestBed.runInInjectionContext(() =>
      authGuard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
    ) as Promise<boolean | UrlTree>;
  };

  it('redirects to /login when the refresh fails (inject must not run after await)', async () => {
    const result = await run({
      isAuthenticated: () => false,
      refresh: () => Promise.resolve(false),
    } as never);
    expect(result instanceof UrlTree).toBe(true);
    expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/login');
  });

  it('allows navigation after a successful refresh', async () => {
    expect(
      await run({ isAuthenticated: () => false, refresh: () => Promise.resolve(true) } as never),
    ).toBe(true);
  });
});
