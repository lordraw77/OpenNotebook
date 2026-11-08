import { HttpClient, HttpEvent, HttpEventType, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, filter, firstValueFrom, map } from 'rxjs';

// Types mirroring backend/src/opennotebook/api/{sources,notes,ingestion_status}.py

export type SourceStatus = 'queued' | 'parsing' | 'chunking' | 'embedding' | 'ready' | 'failed';
export const TERMINAL: SourceStatus[] = ['ready', 'failed'];

export interface SourceDto {
  id: string;
  notebook_id: string;
  kind: 'file' | 'code' | 'image' | 'web' | 'note' | 'archive';
  title: string;
  original_path: string | null;
  mime_type: string | null;
  size_bytes: number;
  active: boolean;
  status: SourceStatus;
  error: { code: string; message: string; attempt?: number; final?: boolean } | null;
  warnings: string[];
  chunk_count: number;
  page_count: number | null;
  embedding_model_id: string | null;
  note_id: string | null;
  parent_source_id: string | null;
  uri: string | null;
  language: string | null;
  summary: string | null;
  suggested_questions: string[];
  summary_status: 'pending' | 'done' | 'failed' | 'skipped' | null;
  summary_error: string | null;
  graph_status: 'pending' | 'done' | 'failed' | 'skipped' | null;
  graph_error: string | null;
  details: {
    archive?: {
      format: string;
      files: number;
      skipped_count: number;
      skipped: { path: string; reason: string }[];
      uncompressed_bytes: number;
      depth: number;
    };
    final_url?: string;
    content_type?: string;
    fetched_at?: string;
    crawl?: { root: string; depth_left: number; max_pages: number; links_followed?: number };
  };
  created_at: string;
  indexed_at: string | null;
}

export interface UploadResult {
  filename: string;
  source: SourceDto | null;
  duplicate: boolean;
  error: string | null;
}

export interface ChunkDto {
  id: string;
  ordinal: number;
  text: string;
  heading_path: string[];
  page_start: number | null;
  page_end: number | null;
  line_start: number | null;
  line_end: number | null;
  char_start: number;
  char_end: number;
  token_count: number;
  block_type: string;
}

export interface SearchHit {
  score: number;
  chunk: ChunkDto;
  source_id: string;
  source_title: string;
  notebook_id: string;
  notebook_name: string;
}

export interface NoteDto {
  id: string;
  notebook_id: string;
  title: string;
  body_md: string;
  origin: string;
  citations: Citation[];
  indexed: boolean;
  source_id: string | null;
  source_status: SourceStatus | null;
  created_at: string;
  updated_at: string;
}

/** A passage given to the chat model (S<n>) or cited by an answer or a note. */
export interface Citation {
  n: number;
  chunk_id: string;
  source_id: string;
  source_title: string;
  source_kind: SourceDto['kind'];
  mime_type: string | null;
  notebook_id: string;
  notebook_name: string;
  heading_path: string[];
  page_start: number | null;
  page_end: number | null;
  line_start: number | null;
  line_end: number | null;
  char_start: number;
  char_end: number;
  bboxes: { page: number; x0: number; top: number; x1: number; bottom: number }[];
  text?: string;
  excerpt?: string;
  score?: number;
  /** how the passage reached the chat context */
  via?: 'search' | 'graph';
}

/** "p. 4", "pp. 4–5", "lines 10–24" or "" — the model never writes these, the client does. */
export function citationLocation(
  c: Pick<Citation, 'page_start' | 'page_end' | 'line_start' | 'line_end'>,
): string {
  if (c.page_start) {
    return !c.page_end || c.page_end === c.page_start
      ? `p. ${c.page_start}`
      : `pp. ${c.page_start}–${c.page_end}`;
  }
  if (c.line_start) {
    return !c.line_end || c.line_end === c.line_start
      ? `line ${c.line_start}`
      : `lines ${c.line_start}–${c.line_end}`;
  }
  return '';
}

export interface IngestionStatus {
  by_status: Record<SourceStatus, number>;
  queues: Record<string, number> | null;
  failed: {
    id: string;
    title: string;
    notebook_id: string;
    error: SourceDto['error'];
    updated_at: string;
  }[];
  projects: {
    project_id: string;
    project_name: string;
    embedding_model: string | null;
    embedding_source: 'project' | 'global' | 'none';
    sources: number;
    chunks: number;
    stale_sources: number;
  }[];
  recent_jobs: {
    source_id: string;
    reason: string;
    status: string;
    attempts: number;
    provider_model: string | null;
    error: string | null;
    created_at: string;
    finished_at: string | null;
  }[];
}

export type UploadEvent = { progress: number } | { done: UploadResult[] };

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

@Injectable({ providedIn: 'root' })
export class SourcesApi {
  private readonly http = inject(HttpClient);

  list(scopeId: string | null = null): Promise<SourceDto[]> {
    const params = scopeId ? new HttpParams().set('scope_id', scopeId) : undefined;
    return firstValueFrom(this.http.get<SourceDto[]>('/api/sources', { params }));
  }

  get(id: string): Promise<SourceDto> {
    return firstValueFrom(this.http.get<SourceDto>(`/api/sources/${id}`));
  }

  /** Multipart upload with progress (0..1) followed by the per-file results. */
  upload(notebookId: string, files: File[]): Observable<UploadEvent> {
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);
    return this.http
      .post<UploadResult[]>(`/api/nodes/${notebookId}/sources`, form, {
        reportProgress: true,
        observe: 'events',
      })
      .pipe(
        filter(
          (e: HttpEvent<UploadResult[]>) =>
            e.type === HttpEventType.UploadProgress || e.type === HttpEventType.Response,
        ),
        map((e): UploadEvent =>
          e.type === HttpEventType.UploadProgress
            ? { progress: e.total ? e.loaded / e.total : 0 }
            : { done: (e as { body: UploadResult[] }).body },
        ),
      );
  }

  update(id: string, body: Partial<{ title: string; active: boolean }>): Promise<SourceDto> {
    return firstValueFrom(this.http.patch<SourceDto>(`/api/sources/${id}`, body));
  }

  remove(id: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`/api/sources/${id}`));
  }

  reindex(id: string): Promise<SourceDto> {
    return firstValueFrom(this.http.post<SourceDto>(`/api/sources/${id}/reindex`, {}));
  }

  chunks(id: string, offset = 0, limit = 50): Promise<ChunkDto[]> {
    const params = new HttpParams().set('offset', offset).set('limit', limit);
    return firstValueFrom(this.http.get<ChunkDto[]>(`/api/sources/${id}/chunks`, { params }));
  }

  /** Normalized text that chunk character offsets refer to. */
  text(id: string): Promise<string> {
    return firstValueFrom(this.http.get(`/api/sources/${id}/text`, { responseType: 'text' }));
  }

  /** Original file bytes (e.g. a PDF for the viewer). */
  fileBytes(id: string): Promise<ArrayBuffer> {
    return firstValueFrom(
      this.http.get(`/api/sources/${id}/file`, { responseType: 'arraybuffer' }),
    );
  }

  /** Downloads the original file with the bearer token and saves it through a temporary object URL. */
  async download(source: SourceDto): Promise<void> {
    const blob = await firstValueFrom(
      this.http.get(`/api/sources/${source.id}/file`, { responseType: 'blob' }),
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = source.title;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /** Adds web pages by URL (fetched and indexed by the worker); optional same-site crawl. */
  addWeb(
    notebookId: string,
    urls: string[],
    crawlDepth = 0,
    maxPages: number | null = null,
  ): Promise<UploadResult[]> {
    return firstValueFrom(
      this.http.post<UploadResult[]>(`/api/nodes/${notebookId}/web`, {
        urls,
        crawl_depth: crawlDepth,
        max_pages: maxPages,
      }),
    );
  }

  search(
    scopeId: string,
    query: string,
    limit = 10,
  ): Promise<{ embedding_model: string; hits: SearchHit[] }> {
    return firstValueFrom(
      this.http.post<{ embedding_model: string; hits: SearchHit[] }>('/api/search', {
        scope_id: scopeId,
        query,
        limit,
      }),
    );
  }

  notes(notebookId: string): Promise<NoteDto[]> {
    return firstValueFrom(this.http.get<NoteDto[]>(`/api/nodes/${notebookId}/notes`));
  }

  createNote(
    notebookId: string,
    body: { title: string; body_md: string; indexed: boolean; from_message_id?: string },
  ): Promise<NoteDto> {
    return firstValueFrom(this.http.post<NoteDto>(`/api/nodes/${notebookId}/notes`, body));
  }

  updateNote(
    id: string,
    body: Partial<{ title: string; body_md: string; indexed: boolean }>,
  ): Promise<NoteDto> {
    return firstValueFrom(this.http.patch<NoteDto>(`/api/notes/${id}`, body));
  }

  deleteNote(id: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`/api/notes/${id}`));
  }

  ingestionStatus(): Promise<IngestionStatus> {
    return firstValueFrom(this.http.get<IngestionStatus>('/api/ingestion/status'));
  }

  rebuildProjectGraph(projectId: string): Promise<{ queued: number }> {
    return firstValueFrom(
      this.http.post<{ queued: number }>(`/api/ingestion/projects/${projectId}/graph`, {}),
    );
  }

  reindexProject(projectId: string): Promise<{ queued: number }> {
    return firstValueFrom(
      this.http.post<{ queued: number }>(`/api/ingestion/projects/${projectId}/reindex`, {}),
    );
  }
}
