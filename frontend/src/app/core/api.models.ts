import { i18nKey } from './i18n';

// Types mirroring the backend API (backend/src/opennotebook/api).

export type NodeKind = 'project' | 'workspace' | 'notebook';
export type GrantRole = 'viewer' | 'editor' | 'owner';
export type ModelPhase =
  'embedding' | 'rerank' | 'chat' | 'summary' | 'vision' | 'ocr' | 'graph_extraction';
export type ProviderKind =
  | 'groq'
  | 'openrouter'
  | 'gemini'
  | 'cloudflare'
  | 'cerebras'
  | 'mistral'
  | 'nvidia'
  | 'huggingface'
  | 'ollama';

export const BASE_CAPABILITIES: ModelPhase[] = ['chat', 'vision', 'embedding', 'rerank', 'ocr'];

export const PHASE_LABELS: Record<ModelPhase, string> = {
  chat: i18nKey('Chat'),
  summary: i18nKey('Summary & suggested questions'),
  graph_extraction: i18nKey('Graph extraction'),
  vision: i18nKey('Image description'),
  ocr: i18nKey('OCR'),
  embedding: i18nKey('Embedding'),
  rerank: i18nKey('Rerank'),
};

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface TreeNodeDto {
  id: string;
  kind: NodeKind;
  parent_id: string | null;
  name: string;
  slug: string;
  depth: number;
  active: boolean;
  role: GrantRole | null;
  project_id: string;
}

export interface Grant {
  principal_type: 'user' | 'group';
  principal_id: string;
  role: GrantRole;
  principal_name?: string | null;
}

export interface ProviderKindInfo {
  kind: ProviderKind;
  label: string;
  requires_api_key: boolean;
  requires_base_url: boolean;
  option_keys: string[];
}

export interface Provider {
  id: string;
  kind: ProviderKind;
  label: string;
  name: string;
  base_url: string | null;
  options: Record<string, string>;
  enabled: boolean;
  timeout_s: number;
  api_key_hint: string | null;
  last_sync_at: string | null;
  last_error: string | null;
  model_count: number;
  enabled_model_count: number;
}

export interface ProviderModel {
  id: string;
  provider_id: string;
  provider_name: string;
  provider_kind: ProviderKind;
  model: string;
  display_name: string | null;
  capabilities: ModelPhase[];
  capabilities_source: string;
  context_window: number | null;
  embedding_dim: number | null;
  enabled: boolean;
  available: boolean;
}

export interface ChainItem {
  position: number;
  model: ProviderModel;
  params: Record<string, unknown>;
}

export interface PhaseAssignment {
  phase: ModelPhase;
  single_model: boolean;
  required_capabilities: ModelPhase[];
  global_chain: ChainItem[];
  project_chain: ChainItem[] | null;
  effective: ChainItem[];
  source: 'project' | 'global' | 'none';
}

export interface ComponentStatus {
  name: string;
  ok: boolean;
  latency_ms?: number;
  error?: string;
}

export interface ModelTestResult {
  ok: boolean;
  latency_ms?: number;
  kind?: string;
  reply?: string;
  embedding_dim?: number;
  error?: string;
  status_code?: number | null;
  detail?: string;
}
