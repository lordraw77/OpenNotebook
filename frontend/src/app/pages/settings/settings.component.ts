import { Component, inject } from '@angular/core';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-settings',
  imports: [MatTabsModule, RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <div class="page">
      <h1>Settings</h1>
      <nav mat-tab-nav-bar [tabPanel]="panel" aria-label="Settings sections">
        <a
          mat-tab-link
          routerLink="models"
          routerLinkActive
          #m="routerLinkActive"
          [active]="m.isActive"
          >Models</a
        >
        @if (auth.isAdmin()) {
          <a
            mat-tab-link
            routerLink="providers"
            routerLinkActive
            #p="routerLinkActive"
            [active]="p.isActive"
            >Providers</a
          >
          <a
            mat-tab-link
            routerLink="users"
            routerLinkActive
            #u="routerLinkActive"
            [active]="u.isActive"
            >Users</a
          >
        }
      </nav>
      <mat-tab-nav-panel #panel><router-outlet /></mat-tab-nav-panel>
    </div>
  `,
})
export class SettingsComponent {
  protected readonly auth = inject(AuthService);
}
