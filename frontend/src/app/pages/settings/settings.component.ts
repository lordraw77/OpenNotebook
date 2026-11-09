import { Component, inject } from '@angular/core';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/auth.service';
import { TranslatePipe, t } from '../../core/i18n';

@Component({
  selector: 'app-settings',
  imports: [TranslatePipe, MatTabsModule, RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <div class="page">
      <h1>{{ 'Settings' | t }}</h1>
      <nav mat-tab-nav-bar [tabPanel]="panel" [attr.aria-label]="'Settings sections' | t">
        <a
          mat-tab-link
          routerLink="models"
          routerLinkActive
          #m="routerLinkActive"
          [active]="m.isActive"
          >{{ 'Models' | t }}</a
        >
        @if (auth.isAdmin()) {
          <a
            mat-tab-link
            routerLink="providers"
            routerLinkActive
            #p="routerLinkActive"
            [active]="p.isActive"
            >{{ 'Providers' | t }}</a
          >
          <a
            mat-tab-link
            routerLink="users"
            routerLinkActive
            #u="routerLinkActive"
            [active]="u.isActive"
            >{{ 'Users' | t }}</a
          >
          <a
            mat-tab-link
            routerLink="groups"
            routerLinkActive
            #g="routerLinkActive"
            [active]="g.isActive"
            >{{ 'Groups' | t }}</a
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
