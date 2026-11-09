import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  ComponentStatus,
  Grant,
  ModelPhase,
  ModelTestResult,
  NodeKind,
  PhaseAssignment,
  Provider,
  ProviderKindInfo,
  ProviderModel,
  TreeNodeDto,
  User,
} from './api.models';
import { i18nKey, t } from './i18n';

/** Server messages users meet most often; others are shown in English as the API returns them. */
export const SERVER_MESSAGES = [
  i18nKey('Invalid email or password'),
  i18nKey('Too many login attempts, retry later'),
  i18nKey('User disabled'),
  i18nKey('Password sign-in is disabled: use single sign-on'),
  i18nKey('Too many questions: wait a minute and retry'),
  i18nKey('Too many searches: wait a minute and retry'),
  i18nKey('Deep research limit reached for this hour'),
  i18nKey('A sibling with the same name already exists'),
  i18nKey('A project must keep at least one owner'),
  i18nKey('Administrator role required'),
  i18nKey('Ingestion already in progress'),
];

export function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) return t('The server cannot be reached. Check the connection and retry.');
    const detail = err.error?.detail;
    if (typeof detail === 'string') return t(detail);
    if (Array.isArray(detail)) return detail.map((d) => d.msg ?? String(d)).join('; ');
    return `${err.status} ${err.statusText}`;
  }
  return err instanceof Error ? err.message : String(err);
}

/** Thin promise-based client for the OpenNotebook API. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  private get<T>(
    url: string,
    params?: Record<string, string | boolean | null | undefined>,
  ): Promise<T> {
    let p = new HttpParams();
    for (const [k, v] of Object.entries(params ?? {}))
      if (v !== null && v !== undefined && v !== '') p = p.set(k, String(v));
    return firstValueFrom(this.http.get<T>(url, { params: p }));
  }
  private post<T>(url: string, body: unknown = {}): Promise<T> {
    return firstValueFrom(this.http.post<T>(url, body));
  }
  private patch<T>(url: string, body: unknown): Promise<T> {
    return firstValueFrom(this.http.patch<T>(url, body));
  }
  private put<T>(url: string, body: unknown): Promise<T> {
    return firstValueFrom(this.http.put<T>(url, body));
  }
  private delete(url: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(url));
  }

  // Health
  status = () => this.get<{ version: string; components: ComponentStatus[] }>('/api/health/status');

  // Nodes
  nodes = () => this.get<TreeNodeDto[]>('/api/nodes');
  createNode = (kind: NodeKind, name: string, parent_id: string | null) =>
    this.post<TreeNodeDto>('/api/nodes', { kind, name, parent_id });
  updateNode = (id: string, body: Partial<{ name: string; active: boolean; parent_id: string }>) =>
    this.patch<TreeNodeDto>(`/api/nodes/${id}`, body);
  deleteNode = (id: string) => this.delete(`/api/nodes/${id}`);
  grants = (id: string) => this.get<Grant[]>(`/api/nodes/${id}/grants`);
  putGrant = (id: string, grant: Grant) => this.put<Grant>(`/api/nodes/${id}/grants`, grant);
  deleteGrant = (id: string, g: Grant) =>
    this.delete(`/api/nodes/${id}/grants/${g.principal_type}/${g.principal_id}`);

  // Users
  users = () => this.get<User[]>('/api/users');
  userDirectory = (q: string) =>
    this.get<Pick<User, 'id' | 'email' | 'display_name'>[]>('/api/users/directory', { q });
  createUser = (body: {
    email: string;
    display_name: string;
    password: string;
    is_admin: boolean;
  }) => this.post<User>('/api/users', body);
  updateUser = (
    id: string,
    body: Partial<{
      display_name: string;
      password: string;
      is_admin: boolean;
      is_active: boolean;
    }>,
  ) => this.patch<User>(`/api/users/${id}`, body);

  // Providers and models
  providerKinds = () => this.get<ProviderKindInfo[]>('/api/provider-kinds');
  providers = () => this.get<Provider[]>('/api/providers');
  createProvider = (body: {
    kind: string;
    name: string;
    api_key?: string | null;
    base_url?: string | null;
    options?: Record<string, string>;
    timeout_s?: number;
  }) => this.post<Provider>('/api/providers', body);
  updateProvider = (
    id: string,
    body: Partial<{
      api_key: string;
      base_url: string;
      options: Record<string, string>;
      enabled: boolean;
      timeout_s: number;
    }>,
  ) => this.patch<Provider>(`/api/providers/${id}`, body);
  deleteProvider = (id: string) => this.delete(`/api/providers/${id}`);
  syncProvider = (id: string) =>
    this.post<{ discovered: number; added: number; updated: number; unavailable: number }>(
      `/api/providers/${id}/sync`,
    );
  providerModels = (
    id: string,
    filters: { capability?: string | null; q?: string; enabled_only?: boolean } = {},
  ) => this.get<ProviderModel[]>(`/api/providers/${id}/models`, filters);
  addModel = (providerId: string, body: { model: string; capabilities: ModelPhase[] }) =>
    this.post<ProviderModel>(`/api/providers/${providerId}/models`, body);
  updateModel = (id: string, body: Partial<{ enabled: boolean; capabilities: ModelPhase[] }>) =>
    this.patch<ProviderModel>(`/api/provider-models/${id}`, body);
  testModel = (id: string) => this.post<ModelTestResult>(`/api/provider-models/${id}/test`);

  // Model selection
  assignments = (projectId: string | null) =>
    this.get<PhaseAssignment[]>('/api/model-assignments', { project_id: projectId });
  putAssignment = (phase: ModelPhase, modelIds: string[], projectId: string | null) =>
    this.put<PhaseAssignment>(`/api/model-assignments/${phase}`, {
      model_ids: modelIds,
      project_id: projectId,
    });
  selectableModels = (phase: ModelPhase, projectId: string | null, includeAll = false) =>
    this.get<ProviderModel[]>('/api/models/selectable', {
      phase,
      project_id: projectId,
      include_all: includeAll,
    });
}
