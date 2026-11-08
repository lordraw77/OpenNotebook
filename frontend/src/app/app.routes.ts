import { Routes } from '@angular/router';

import { adminGuard, authGuard } from './core/guards';
import { ShellComponent } from './layout/shell.component';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./pages/login/login.component').then((m) => m.LoginComponent),
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'workbench' },
      {
        path: 'workbench',
        title: 'Workbench · OpenNotebook',
        loadComponent: () =>
          import('./pages/workbench/workbench.component').then((m) => m.WorkbenchComponent),
      },
      {
        path: 'upload',
        title: 'Upload · OpenNotebook',
        loadComponent: () =>
          import('./pages/upload/upload.component').then((m) => m.UploadComponent),
      },
      {
        path: 'wiki',
        title: 'Wiki · OpenNotebook',
        loadComponent: () => import('./pages/wiki/wiki.component').then((m) => m.WikiComponent),
      },
      {
        path: 'status',
        title: 'RAG Status · OpenNotebook',
        loadComponent: () =>
          import('./pages/status/status.component').then((m) => m.StatusComponent),
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./pages/settings/settings.component').then((m) => m.SettingsComponent),
        children: [
          { path: '', pathMatch: 'full', redirectTo: 'models' },
          {
            path: 'models',
            title: 'Models · OpenNotebook',
            loadComponent: () =>
              import('./pages/settings/models.component').then((m) => m.ModelsComponent),
          },
          {
            path: 'providers',
            title: 'Providers · OpenNotebook',
            canActivate: [adminGuard],
            loadComponent: () =>
              import('./pages/settings/providers.component').then((m) => m.ProvidersComponent),
          },
          {
            path: 'users',
            title: 'Users · OpenNotebook',
            canActivate: [adminGuard],
            loadComponent: () =>
              import('./pages/settings/users.component').then((m) => m.UsersComponent),
          },
        ],
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
