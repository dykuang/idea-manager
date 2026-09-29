import type { AgentChatSession, AgentChatSessionDetails, AgentMessage, AgentMode, AgentProvider, AgentRunResult, AgentRunSaveResult, AgentStatus, Attachment, Idea, MicroExperiment, Project, ProjectGroup, ProjectSyncPreview, RemoteMachine, RemoteStatus, ReasoningEffort, Relation, ResearchGap, ResearchIntelligenceSettings, ReviewData, SemanticOpportunity, SemanticStatus, SerendipityPair, Status, Suggestion, SyncPreviewItem, TagInfo, TagMapData } from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export interface ImportPreview {
  version: number
  counts: { groups: number; projects: number; ideas: number; relations: number; experiments?: number }
  duplicate_topics: number
  project_conflicts: string[]
  group_conflicts: string[]
}

export interface ImportResult {
  status: string
  groups_created: number
  projects_created: number
  ideas_created: number
  ideas_skipped: number
  ideas_updated: number
  relations_created: number
  experiments_created: number
}

export const api = {
  libraryState: () => request<{ revision: number }>('/library-state'),
  ideas: (params: URLSearchParams) => request<Idea[]>(`/ideas?${params}`),
  idea: (id: number) => request<Idea & { relations: Relation[]; attachments: Attachment[] }>(`/ideas/${id}`),
  createIdea: (data: { title: string; content: string; raw_text: string; status: Status; tags: string[]; project_id: number }) =>
    request<Idea>('/ideas', { method: 'POST', body: JSON.stringify(data) }),
  updateIdea: (id: number, data: { title: string; content: string; status: Status; tags: string[]; expected_updated_at?: string }) =>
    request<Idea>(`/ideas/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteIdea: (id: number, permanent = false) => request<{ action: 'recycled' | 'deleted' }>(`/ideas/${id}?permanent=${permanent}`, { method: 'DELETE' }),
  moveIdea: (id: number, project_id: number) => request<Idea>(`/ideas/${id}/move`, { method: 'POST', body: JSON.stringify({ project_id }) }),
  copyIdea: (id: number, project_id: number) => request<Idea>(`/ideas/${id}/copy`, { method: 'POST', body: JSON.stringify({ project_id }) }),
  projects: () => request<Project[]>('/projects'),
  createProject: (data: { name: string; description: string; group_id: number | null; workspace_mode: 'library' | 'linked' | 'managed'; workspace_path: string }) => request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
  clearProject: (id: number) => request<{ action: 'recycled' | 'deleted'; count: number }>(`/projects/${id}/ideas`, { method: 'DELETE' }),
  projectGroups: () => request<ProjectGroup[]>('/project-groups'),
  remoteMachines: () => request<RemoteMachine[]>('/remotes'),
  createRemoteMachine: (data: Omit<RemoteMachine, 'id' | 'created_at' | 'updated_at'>) => request<RemoteMachine>('/remotes', { method: 'POST', body: JSON.stringify(data) }),
  updateRemoteMachine: (id: number, data: Omit<RemoteMachine, 'id' | 'created_at' | 'updated_at'>) => request<RemoteMachine>(`/remotes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteRemoteMachine: (id: number) => request<{ id: number }>(`/remotes/${id}`, { method: 'DELETE' }),
  checkRemoteMachine: (id: number) => request<RemoteStatus>(`/remotes/${id}/check`, { method: 'POST' }),
  previewProjectSync: (data: { machine_id: number; project_id: number; direction: 'push' | 'pull'; local_root: string }) => request<ProjectSyncPreview>('/project-sync/preview', { method: 'POST', body: JSON.stringify(data) }),
  executeProjectSync: (data: { preview_id: string; selected_paths: string[]; delete_paths: string[] }) => request<{ transferred: number; deleted: number; skipped: number; project_name: string; direction: 'push' | 'pull' }>('/project-sync/execute', { method: 'POST', body: JSON.stringify(data) }),
  createProjectGroup: (name: string) => request<ProjectGroup>('/project-groups', { method: 'POST', body: JSON.stringify({ name }) }),
  previewImport: (data: Record<string, unknown>) => request<ImportPreview>('/import/preview', { method: 'POST', body: JSON.stringify({ data }) }),
  importJson: (data: Record<string, unknown>, duplicate_strategy: 'skip' | 'copy' | 'update', project_strategy: 'merge' | 'rename') => request<ImportResult>('/import/json', { method: 'POST', body: JSON.stringify({ data, duplicate_strategy, project_strategy }) }),
  tags: (params = new URLSearchParams()) => request<TagInfo[]>(`/tags?${params}`),
  tagMap: (params = new URLSearchParams()) => request<TagMapData>(`/tags/map?${params}`),
  managedTags: () => request<(TagInfo & { is_hidden: boolean })[]>('/tags/manage'),
  updateTagSettings: (name: string, data: { group_name: string; is_hidden: boolean }) => request<TagInfo>(`/tags/${encodeURIComponent(name)}/settings`, { method: 'PUT', body: JSON.stringify(data) }),
  renameTag: (name: string, nextName: string) => request<{ name: string; merged: boolean }>(`/tags/${encodeURIComponent(name)}/rename`, { method: 'POST', body: JSON.stringify({ name: nextName }) }),
  mergeTag: (name: string, targetName: string) => request<{ name: string; merged: boolean }>(`/tags/${encodeURIComponent(name)}/merge`, { method: 'POST', body: JSON.stringify({ target_name: targetName }) }),
  bulkUpdateTags: (data: { idea_ids: number[]; add_tags: string[]; remove_tags: string[] }) => request<{ ideas_updated: number }>('/tags/bulk', { method: 'POST', body: JSON.stringify(data) }),
  relations: () => request<Relation[]>('/relations'),
  relationTypes: () => request<string[]>('/relation-types'),
  createRelation: (data: Omit<Relation, 'id'>) => request<Relation>('/relations', { method: 'POST', body: JSON.stringify(data) }),
  deleteRelation: (id: number) => request<void>(`/relations/${id}`, { method: 'DELETE' }),
  suggestions: (id: number) => request<Suggestion[]>(`/ideas/${id}/suggestions`),
  semanticStatus: () => request<SemanticStatus>('/semantic/status'),
  rebuildSemantic: () => request<SemanticStatus>('/semantic/rebuild', { method: 'POST' }),
  semanticOpportunities: (params = new URLSearchParams()) => request<SemanticOpportunity[]>(`/semantic/opportunities?${params}`),
  review: (params = new URLSearchParams()) => request<ReviewData>(`/review?${params}`),
  experiments: (params = new URLSearchParams()) => request<MicroExperiment[]>(`/experiments?${params}`),
  createExperiment: (data: { what_tried: string; result: string; takeaway: string; status: MicroExperiment['status']; dataset_material: string; metrics: Record<string, unknown>; code_ref: string; metadata: Record<string, unknown>; idea_links: { idea_id: number; role: string }[]; attachment_ids: number[] }) => request<MicroExperiment>('/experiments', { method: 'POST', body: JSON.stringify(data) }),
  updateExperiment: (id: number, data: { what_tried: string; result: string; takeaway: string; status: MicroExperiment['status']; dataset_material: string; metrics: Record<string, unknown>; code_ref: string; metadata: Record<string, unknown>; idea_links: { idea_id: number; role: string }[]; attachment_ids: number[] }) => request<MicroExperiment>(`/experiments/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  repeatMatches: (q: string, idea_id?: number) => request<(MicroExperiment & { score: number; linked_to_idea: boolean; feedback_key: string })[]>(`/experiments/repeat-detection/matches?${new URLSearchParams({ q, ...(idea_id ? { idea_id: String(idea_id) } : {}) })}`),
  researchSettings: () => request<ResearchIntelligenceSettings>('/research-intelligence/settings'),
  updateResearchSettings: (data: Partial<ResearchIntelligenceSettings>) => request<ResearchIntelligenceSettings>('/research-intelligence/settings', { method: 'PUT', body: JSON.stringify(data) }),
  researchGaps: (params = new URLSearchParams()) => request<ResearchGap[]>(`/research-intelligence/gaps?${params}`),
  experimentReview: (params = new URLSearchParams()) => request<{ recently_completed: MicroExperiment[]; inconclusive: MicroExperiment[]; failed: MicroExperiment[]; untouched_planned: MicroExperiment[] }>(`/research-intelligence/weekly-review?${params}`),
  insightFeedback: (data: { concept: 'serendipity' | 'research-gap' | 'experiment-repeat'; subject_key: string; action: 'dismissed' | 'saved' | 'resolved' | 'snoozed' | 'accepted'; snooze_until?: string; metadata?: Record<string, unknown> }) => request('/research-intelligence/feedback', { method: 'POST', body: JSON.stringify(data) }),
  serendipity: (params = new URLSearchParams()) => request<SerendipityPair[]>(`/serendipity?${params}`),
  agentStatus: () => request<AgentStatus>('/agent/status'),
  configureAgent: (data: { provider: AgentProvider; api_key: string; model: string; base_url: string; reasoning_effort: ReasoningEffort; remember_api_key: boolean }) => request<AgentStatus>('/agent/config', { method: 'POST', body: JSON.stringify(data) }),
  activateAgentProvider: (provider: AgentProvider) => request<AgentStatus>(`/agent/activate/${provider}`, { method: 'POST' }),
  forgetAgentProfile: (provider: AgentProvider) => request<AgentStatus>(`/agent/config/${provider}`, { method: 'DELETE' }),
  clearAgentConfig: () => request<AgentStatus>('/agent/config', { method: 'DELETE' }),
  agentSessions: () => request<AgentChatSession[]>('/agent/sessions'),
  agentSession: (id: number) => request<AgentChatSessionDetails>(`/agent/sessions/${id}`),
  pickFolder: (initial_path = '') => request<{ path: string }>('/system/pick-folder', { method: 'POST', body: JSON.stringify({ initial_path }) }),
  pickFile: (initial_path = '') => request<{ path: string }>('/system/pick-file', { method: 'POST', body: JSON.stringify({ initial_path }) }),
  attachments: (params = new URLSearchParams()) => request<Attachment[]>(`/attachments?${params}`),
  attachFile: (ideaId: number, path: string, storage_mode: 'linked' | 'managed') => request<Attachment>(`/ideas/${ideaId}/attachments`, { method: 'POST', body: JSON.stringify({ path, storage_mode }) }),
  uploadFigure: async (ideaId: number, file: File) => {
    const form = new FormData(); form.append('file', file)
    const response = await fetch(`/api/ideas/${ideaId}/figures`, { method: 'POST', body: form })
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Upload failed (${response.status})`) }
    return response.json() as Promise<Attachment>
  },
  updateIdeaAttachment: (ideaId: number, attachmentId: number, data: Partial<Pick<Attachment, 'asset_role' | 'caption' | 'sort_order' | 'is_cover'>>) =>
    request<Attachment>(`/ideas/${ideaId}/attachments/${attachmentId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  detachFile: (ideaId: number, attachmentId: number) => request<void>(`/ideas/${ideaId}/attachments/${attachmentId}`, { method: 'DELETE' }),
  openAttachment: (id: number) => request<{ status: string }>(`/attachments/${id}/open`, { method: 'POST' }),
  revealAttachment: (id: number) => request<{ status: string }>(`/attachments/${id}/reveal`, { method: 'POST' }),
  runAgent: (data: { prompt: string; conversation: AgentMessage[]; session_id: number | null; mode: AgentMode; scope_type: 'all' | 'project' | 'group'; scope_id: number | null; idea_id: number | null; context_idea_ids: number[]; model: string; reasoning_effort: ReasoningEffort; web_search: boolean; attachment_ids: number[] }) =>
    request<AgentRunResult>('/agent/runs', { method: 'POST', body: JSON.stringify(data) }),
  dream: (data: { idea_ids: number[]; prompt: string; project_id: number; model: string }) =>
    request<AgentRunResult>('/dreams', { method: 'POST', body: JSON.stringify(data) }),
  saveAgentResult: (id: number, action: 'update_original' | 'create_child') =>
    request<AgentRunSaveResult>(`/agent/runs/${id}/save`, { method: 'POST', body: JSON.stringify({ action }) }),
  resolveAgentProposal: (id: number, action: 'apply' | 'dismiss') =>
    request<{ id: number; status: 'applied' | 'dismissed' }>(`/agent/proposals/${id}`, { method: 'POST', body: JSON.stringify({ action }) }),
  quit: () => request<{ status: string }>('/system/quit', { method: 'POST' }),
}
