import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Citation } from './sources.api';

// Types mirroring backend/src/opennotebook/api/graph.py

export interface EntityDto {
  id: string;
  name: string;
  type: string;
  mentions: number;
  sources: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
}

export interface RelatedEntity {
  entity_id: string;
  name: string;
  type: string;
  relation: string;
  direction: 'in' | 'out';
  description: string | null;
  count: number;
  relation_id: string;
  manual: boolean;
}

export interface EntityDetail {
  id: string;
  name: string;
  aliases: string[];
  type: string;
  descriptions: string[];
  mention_count: number;
  mentions: (Citation & { description: string | null })[];
  related: RelatedEntity[];
}

export interface WikiPageDto {
  body_md: string;
  citations: Citation[];
  model_label: string | null;
  generated_at: string | null;
  cached: boolean;
}

export const ENTITY_TYPES = Object.keys({
  person: 1,
  organization: 1,
  product: 1,
  component: 1,
  technology: 1,
  concept: 1,
  location: 1,
  event: 1,
  document: 1,
  standard: 1,
  file: 1,
  function: 1,
  class: 1,
  struct: 1,
  interface: 1,
  module: 1,
});

export const ENTITY_ICONS: Record<string, string> = {
  person: 'person',
  organization: 'corporate_fare',
  product: 'inventory_2',
  component: 'memory',
  technology: 'developer_board',
  concept: 'lightbulb',
  location: 'place',
  event: 'event',
  document: 'description',
  standard: 'verified',
  file: 'draft',
  function: 'function',
  class: 'data_object',
  struct: 'data_object',
  interface: 'integration_instructions',
  module: 'package_2',
};

@Injectable({ providedIn: 'root' })
export class GraphApi {
  private readonly http = inject(HttpClient);

  entities(scopeId: string, q = '', types: string[] = [], limit = 200): Promise<EntityDto[]> {
    let params = new HttpParams().set('scope_id', scopeId).set('limit', limit);
    if (q.trim()) params = params.set('q', q.trim());
    for (const t of types) params = params.append('type', t);
    return firstValueFrom(this.http.get<EntityDto[]>('/api/entities', { params }));
  }

  graph(scopeId: string, limit = 150): Promise<{ nodes: EntityDto[]; edges: GraphEdge[] }> {
    const params = new HttpParams().set('scope_id', scopeId).set('limit', limit);
    return firstValueFrom(
      this.http.get<{ nodes: EntityDto[]; edges: GraphEdge[] }>('/api/graph', { params }),
    );
  }

  entity(id: string, scopeId: string): Promise<EntityDetail> {
    const params = new HttpParams().set('scope_id', scopeId);
    return firstValueFrom(this.http.get<EntityDetail>(`/api/entities/${id}`, { params }));
  }

  wiki(id: string, scopeId: string, refresh = false): Promise<WikiPageDto> {
    const params = new HttpParams().set('scope_id', scopeId).set('refresh', refresh);
    return firstValueFrom(this.http.post<WikiPageDto>(`/api/entities/${id}/wiki`, {}, { params }));
  }

  // graph editor: the backend requires the editor role on the project
  editEntity(
    id: string,
    scopeId: string,
    body: { name?: string; type?: string },
  ): Promise<EntityDetail> {
    const params = new HttpParams().set('scope_id', scopeId);
    return firstValueFrom(this.http.patch<EntityDetail>(`/api/entities/${id}`, body, { params }));
  }

  mergeEntity(id: string, scopeId: string, targetId: string): Promise<EntityDetail> {
    const params = new HttpParams().set('scope_id', scopeId);
    return firstValueFrom(
      this.http.post<EntityDetail>(
        `/api/entities/${id}/merge`,
        { target_id: targetId },
        { params },
      ),
    );
  }

  deleteEntity(id: string, scopeId: string): Promise<void> {
    const params = new HttpParams().set('scope_id', scopeId);
    return firstValueFrom(this.http.delete<void>(`/api/entities/${id}`, { params }));
  }

  addRelation(
    scopeId: string,
    sourceId: string,
    targetId: string,
    type: string,
    description: string,
  ): Promise<{ id: string }> {
    return firstValueFrom(
      this.http.post<{ id: string }>('/api/relations', {
        scope_id: scopeId,
        source_id: sourceId,
        target_id: targetId,
        type,
        description: description || null,
      }),
    );
  }

  deleteRelation(id: string, scopeId: string): Promise<void> {
    const params = new HttpParams().set('scope_id', scopeId);
    return firstValueFrom(this.http.delete<void>(`/api/relations/${id}`, { params }));
  }
}
