import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

// Types mirroring backend/src/opennotebook/api/{groups,projects,auth}.py

export interface GroupDto {
  id: string;
  name: string;
  description: string | null;
  source: 'local' | 'oidc';
  members: number;
}

export interface MemberDto {
  id: string;
  email: string;
  display_name: string;
}

export interface ProjectSettingsDto {
  project_id: string;
  restricted: boolean;
  providers: { id: string; name: string; kind: string; enabled: boolean; allowed: boolean }[];
  index: {
    serving_model: string | null;
    configured_model: string | null;
    switch_pending: boolean;
    sources: number;
    sources_on_configured_model: number;
    switched_at: string | null;
  };
}

export interface AuthConfig {
  password: boolean;
  oidc: boolean;
  oidc_label: string;
}

@Injectable({ providedIn: 'root' })
export class AdminApi {
  private readonly http = inject(HttpClient);

  groups(): Promise<GroupDto[]> {
    return firstValueFrom(this.http.get<GroupDto[]>('/api/groups'));
  }

  groupDirectory(q: string): Promise<GroupDto[]> {
    return firstValueFrom(
      this.http.get<GroupDto[]>('/api/groups/directory', { params: new HttpParams().set('q', q) }),
    );
  }

  createGroup(name: string, description: string | null): Promise<GroupDto> {
    return firstValueFrom(this.http.post<GroupDto>('/api/groups', { name, description }));
  }

  updateGroup(id: string, body: { name?: string; description?: string }): Promise<GroupDto> {
    return firstValueFrom(this.http.patch<GroupDto>(`/api/groups/${id}`, body));
  }

  deleteGroup(id: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`/api/groups/${id}`));
  }

  members(id: string): Promise<MemberDto[]> {
    return firstValueFrom(this.http.get<MemberDto[]>(`/api/groups/${id}/members`));
  }

  addMember(groupId: string, userId: string): Promise<unknown> {
    return firstValueFrom(this.http.put(`/api/groups/${groupId}/members/${userId}`, {}));
  }

  removeMember(groupId: string, userId: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`/api/groups/${groupId}/members/${userId}`));
  }

  projectSettings(projectId: string): Promise<ProjectSettingsDto> {
    return firstValueFrom(this.http.get<ProjectSettingsDto>(`/api/projects/${projectId}/settings`));
  }

  setPolicy(projectId: string, allowed: string[] | null): Promise<ProjectSettingsDto> {
    return firstValueFrom(
      this.http.put<ProjectSettingsDto>(`/api/projects/${projectId}/policy`, {
        allowed_provider_ids: allowed,
      }),
    );
  }

  authConfig(): Promise<AuthConfig> {
    return firstValueFrom(this.http.get<AuthConfig>('/api/auth/config'));
  }
}
