export type Status = 'seed' | 'exploring' | 'promising' | 'parked'

export interface Idea {
  id: number
  title: string
  content: string
  raw_text: string
  status: Status
  tags: string[]
  created_at: string
  updated_at: string
  project_id: number
  attachments?: Attachment[]
  figure_count?: number
}

export interface Attachment {
  id: number
  project_id: number
  display_name: string
  storage_mode: 'linked' | 'managed'
  mime_type: string
  size_bytes: number
  content_hash: string
  created_at: string
  absolute_path: string
  exists: boolean
  asset_role?: 'attachment' | 'figure'
  caption?: string
  sort_order?: number
  is_cover?: boolean
  preview_url?: string | null
}

export interface ProjectGroup {
  id: number
  name: string
  project_count: number
  idea_count: number
}

export interface Project {
  id: number
  name: string
  description: string
  group_id: number | null
  group_name: string | null
  system_key: 'random_chat' | 'recycle' | null
  idea_count: number
  workspace_mode: 'library' | 'linked' | 'managed'
  workspace_path: string
}

export interface Relation {
  id: number
  source_id: number
  target_id: number
  relation_type: string
  note: string
  source_title?: string
  target_title?: string
}

export interface Suggestion extends Idea {
  score: number
  reason: string
}

export interface TagInfo {
  name: string
  count: number
  group_name: string
  is_hidden?: boolean
}

export interface TagMapData {
  nodes: TagInfo[]
  edges: { source: string; target: string; weight: number }[]
}

export type AgentMode = 'explore' | 'elaborate' | 'critique' | 'connect' | 'synthesize'
export type AgentProvider = 'openai' | 'anthropic' | 'deepseek' | 'qwen' | 'local'
export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface AgentProviderOption {
  id: AgentProvider
  label: string
  configured: boolean
  configuration_source: 'session' | 'secure_storage' | 'environment' | 'none'
  credential_stored: boolean
  model: string
  base_url: string
  reasoning_effort: ReasoningEffort
  models: string[]
  reasoning_efforts: ReasoningEffort[]
  default_model: string
  default_base_url: string
  api_key_required: boolean
  web_search_supported: boolean
}

export interface AgentStatus {
  provider: AgentProvider
  provider_label: string
  configured: boolean
  configuration_source: 'session' | 'secure_storage' | 'environment' | 'none'
  default_model: string
  base_url: string
  reasoning_effort: ReasoningEffort
  web_search_supported: boolean
  providers: AgentProviderOption[]
  credential_store_available: boolean
  capabilities: string[]
  privacy: string
}

export interface AgentProposal {
  id: number
  run_id: number
  action_type: 'create_idea' | 'update_idea' | 'create_relation'
  title: string
  rationale: string
  payload: Record<string, unknown>
  status: 'pending' | 'applied' | 'dismissed'
}

export interface AgentRunResult {
  id: number
  session_id?: number
  provider: string
  model: string
  answer: string
  proposals: AgentProposal[]
  context_summary: { ideas: number; relations: number; files: number; raw_text_shared: boolean }
}

export interface AgentMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface AgentChatSession {
  id: number
  title: string
  provider: string
  model: string
  scope_type: 'all' | 'project' | 'group'
  scope_id: number | null
  idea_id: number | null
  context_idea_ids: number[]
  attachment_ids: number[]
  created_at: string
  updated_at: string
  message_count: number
}

export interface AgentChatSessionDetails {
  session: AgentChatSession
  messages: (AgentMessage & { created_at: string })[]
}

export interface AgentRunSaveResult {
  action: 'update_original' | 'create_child'
  idea: Idea
  parent_id: number
  relation_id: number | null
}

export interface SemanticStatus {
  ready: boolean
  model: string
  dimensions: number
  indexed_ideas: number
  created_at: string | null
}

export interface SemanticOpportunity {
  source_id: number
  source_title: string
  target_id: number
  target_title: string
  score: number
  reason: string
}

export interface ReviewProposal extends AgentProposal {
  provider: string
  model: string
  created_at: string
  run_created_at: string
}

export interface ReviewData {
  summary: { active_ideas: number; new_captures: number; unlinked: number; stale_seeds: number; pending_proposals: number; semantic_opportunities: number }
  new_captures: Idea[]
  unlinked: Idea[]
  stale_seeds: Idea[]
  pending_proposals: ReviewProposal[]
  semantic_opportunities: SemanticOpportunity[]
}

export type ExperimentStatus = 'planned' | 'running' | 'completed' | 'failed' | 'inconclusive' | 'needs_follow_up'
export interface MicroExperiment {
  id: number
  what_tried: string
  result: string
  takeaway: string
  status: ExperimentStatus
  dataset_material: string
  metrics: Record<string, unknown>
  code_ref: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  completed_at: string | null
  ideas: { idea_id: number; title: string; project_id: number; role: string }[]
  attachments: { id: number; display_name: string; mime_type: string; asset_role: 'attachment' | 'figure'; caption: string }[]
}
export interface ResearchIntelligenceSettings {
  experiments_enabled: boolean
  gap_radar_enabled: boolean
  serendipity_enabled: boolean
  stalled_days: number
  serendipity_limit: number
  cross_project: boolean
  evidence_checks: boolean
  experiment_fields: string[]
}
export interface ResearchGap {
  id: string
  type: string
  title: string
  detail: string
  target: { idea_id?: number; experiment_id?: number; relation_id?: number }
  priority: number
}
export interface SerendipityPair {
  source_id: number
  source_title: string
  source_project: string
  target_id: number
  target_title: string
  target_project: string
  score: number
  semantic_similarity: number
  reason: string
  feedback_key: string
}
