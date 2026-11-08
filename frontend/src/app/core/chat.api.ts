import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AuthService } from './auth.service';
import { Citation } from './sources.api';

// Types mirroring backend/src/opennotebook/api/conversations.py and chat/service.py

export interface ConversationDto {
  id: string;
  scope_node_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Attempt {
  model: string;
  ok?: boolean;
  error?: string;
  detail?: string;
}

export interface MessageDto {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  status: 'complete' | 'error' | 'stopped';
  context: Citation[];
  citations: Citation[];
  checks: {
    abstained?: boolean;
    uncited_sentences?: number;
    invalid_citations?: string[];
    embedding_model?: string;
    rerank_model?: string | null;
    warnings?: string[];
  };
  model_label: string | null;
  attempts: Attempt[];
  usage: { prompt_tokens?: number; completion_tokens?: number } | null;
  latency_ms: number | null;
  error: string | null;
  created_at: string | null;
}

export type ChatEvent =
  | { event: 'message'; data: MessageDto }
  | { event: 'status'; data: { stage: 'retrieving' | 'generating' } }
  | {
      event: 'sources';
      data: {
        context: Citation[];
        embedding_model: string;
        rerank_model: string | null;
        warnings: string[];
      };
    }
  | { event: 'provider'; data: { model: string; attempts: Attempt[] } }
  | { event: 'token'; data: { text: string } }
  | { event: 'done'; data: MessageDto }
  | { event: 'error'; data: { message: string } };

/** Splits a server-sent-events buffer into complete events; returns the unparsed remainder. */
export function parseSse(buffer: string): { events: ChatEvent[]; rest: string } {
  const events: ChatEvent[] = [];
  const blocks = buffer.split('\n\n');
  const rest = blocks.pop() ?? '';
  for (const block of blocks) {
    let name = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) name = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event: name, data: JSON.parse(data.join('\n')) } as ChatEvent);
  }
  return { events, rest };
}

@Injectable({ providedIn: 'root' })
export class ChatApi {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  list(scopeId: string): Promise<ConversationDto[]> {
    const params = new HttpParams().set('scope_id', scopeId);
    return firstValueFrom(this.http.get<ConversationDto[]>('/api/conversations', { params }));
  }

  create(scopeId: string): Promise<ConversationDto> {
    return firstValueFrom(
      this.http.post<ConversationDto>('/api/conversations', { scope_id: scopeId }),
    );
  }

  get(id: string): Promise<ConversationDto & { messages: MessageDto[] }> {
    return firstValueFrom(
      this.http.get<ConversationDto & { messages: MessageDto[] }>(`/api/conversations/${id}`),
    );
  }

  rename(id: string, title: string): Promise<ConversationDto> {
    return firstValueFrom(this.http.patch<ConversationDto>(`/api/conversations/${id}`, { title }));
  }

  remove(id: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`/api/conversations/${id}`));
  }

  /**
   * Asks a question and streams the answer. HttpClient buffers responses, so this uses fetch with the
   * bearer token (refreshed once on 401). Aborting the signal stops generation server side.
   */
  async ask(
    conversationId: string,
    content: string,
    modelId: string | null,
    onEvent: (e: ChatEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const send = () =>
      fetch(`/api/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          Authorization: `Bearer ${this.auth.accessToken() ?? ''}`,
        },
        body: JSON.stringify({ content, model_id: modelId }),
        signal,
      });
    let res = await send();
    if (res.status === 401 && (await this.auth.refresh())) res = await send();
    if (!res.ok || !res.body) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (typeof body?.detail === 'string') detail = body.detail;
      } catch {
        // not JSON
      }
      throw new Error(detail);
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const parsed = parseSse(buffer + value);
      buffer = parsed.rest;
      parsed.events.forEach(onEvent);
    }
  }
}
