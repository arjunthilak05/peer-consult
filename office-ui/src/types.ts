export type ProviderId = 'claude' | 'codex' | 'agy';

export type AgentAnimation =
  | 'idle'
  | 'working'
  | 'thinking'
  | 'reading'
  | 'coding'
  | 'reviewing'
  | 'waiting'
  | 'failed'
  | 'completed';

export type OfficeRoom = 'desks' | 'meeting_room' | 'coding_room' | 'review_room';

export interface AgentToolCallLog {
  seq: number;
  timestamp: string;
  stage: string;
  event_type: string;
  summary: string;
  animation_state: AgentAnimation;
  room: OfficeRoom;
}

export interface AgentUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  duration_ms: number;
}

export interface AgentSnapshot {
  id: ProviderId;
  name: string;
  color: string;
  palette: number;
  model: string;
  reasoning_effort: string;
  role: 'adviser' | 'chair' | 'writer' | 'reviewer';
  room: OfficeRoom;
  seat_id: string;
  animation: AgentAnimation;
  current_task: string;
  tool_calls: AgentToolCallLog[];
  elapsed_ms: number;
  usage: AgentUsage;
  latest_output: Record<string, unknown> | null;
  status_badge: string;
}

export interface TaskBoardItem {
  stage: string;
  attempt?: number;
  provider: string;
  status: string;
  duration_ms: number;
  error: string | null;
}

export interface TaskBoardColumn {
  id: string;
  title: string;
  status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  items: TaskBoardItem[];
}

export interface EvidenceItem {
  id: string;
  source: string;
  reference: string;
  claim: string;
  verified: boolean;
}

export interface AssumptionItem {
  id: string;
  assumption: string;
  impact_if_false: string;
  validation_check: string;
}

export interface DisagreementPosition {
  agent_or_proposal: string;
  stance: string;
}

export interface UnresolvedDisagreement {
  topic: string;
  positions: DisagreementPosition[];
  blocking: boolean;
  recommended_resolution: string;
}

export interface ProposalData {
  summary: string;
  assessment: string;
  recommendation: string;
  proposed_approach: string;
  affected_files: string[];
  implementation_steps: string[];
  risks: string[];
  verification_steps: string[];
  evidence: EvidenceItem[];
  assumptions: AssumptionItem[];
  proposed_code: string;
  confidence: string;
}

export interface ProposalCritiqueItem {
  target_proposal: string;
  verdict: string;
  strengths: string[];
  flaws_and_blindspots: string[];
  challenged_assumptions: string[];
  evidence_gaps: string[];
  suggested_improvements: string[];
}

export interface CritiqueData {
  overall_comparison: string;
  critiques: ProposalCritiqueItem[];
  best_elements_to_combine: string[];
  newly_identified_risks: string[];
  unresolved_questions: string[];
  confidence: string;
}

export interface PlanStep {
  step_id: string;
  title: string;
  description: string;
  target_files: string[];
  verification: string;
}

export interface SynthesisData {
  executive_summary: string;
  final_recommendation: string;
  consensus_points: string[];
  rejected_ideas: string[];
  unresolved_disagreements: UnresolvedDisagreement[];
  evidence_ledger: EvidenceItem[];
  assumptions_ledger: AssumptionItem[];
  recommended_writer: ProviderId;
  writer_rationale: string;
  authorized_files: string[];
  forbidden_paths: string[];
  acceptance_criteria: string[];
  verification_commands: string[];
  steps: PlanStep[];
  risks: string[];
  confidence: string;
}

export interface MeetingData {
  chair: ProviderId;
  anonymized_map: Record<string, ProviderId>;
  proposals: Record<string, ProposalData>;
  critiques: Record<string, CritiqueData>;
  synthesis: SynthesisData | null;
  unresolved_disagreements: UnresolvedDisagreement[];
}

export interface PeerReviewFinding {
  severity: string;
  file_path: string;
  line_range: string;
  description: string;
  suggested_fix: string;
}

export interface PeerReviewEntry {
  agent: ProviderId;
  attempt: number;
  output: {
    verdict: string;
    summary: string;
    scope_compliance: boolean;
    acceptance_criteria_met: string[];
    acceptance_criteria_missed: string[];
    findings: PeerReviewFinding[];
    security_concerns: string[];
    verification_assessment: string;
    confidence: string;
  };
}

export interface ExecutionData {
  writer: ProviderId | null;
  approved: boolean;
  worktree_path: string | null;
  branch_name: string | null;
  repair_attempts: number;
  authorized_files: string[];
  forbidden_paths: string[];
  acceptance_criteria: string[];
  changed_files: string[];
  git_diff: string;
  test_passed: boolean | null;
  test_output: string;
  peer_reviews: PeerReviewEntry[];
  pr_draft_path?: string | null;
}

export interface CouncilEventItem {
  seq: number;
  event_id: string;
  run_id: string;
  timestamp: string;
  stage: string;
  agent: string;
  event_type: string;
  animation_state: AgentAnimation;
  room: OfficeRoom;
  message: string;
  payload: Record<string, unknown>;
}

export interface RunSummary {
  run_id: string;
  mode: string;
  state: string;
  question: string;
  chair: ProviderId;
  writer: ProviderId | null;
  created_at: string;
  updated_at: string;
}

export interface ActiveRunInfo extends RunSummary {
  task_id?: string;
  current_stage?: string;
  cwd: string;
  approved: boolean;
  worktree_path: string | null;
  branch_name: string | null;
  repair_attempts: number;
  error: { kind?: string; message?: string } | null;
  report_path: string | null;
}

export interface OfficeSnapshot {
  timestamp: number;
  demo_mode: boolean;
  active_run_id: string | null;
  run: ActiveRunInfo | null;
  runs: RunSummary[];
  agents: Record<ProviderId, AgentSnapshot>;
  task_board: TaskBoardColumn[];
  meeting: MeetingData;
  execution: ExecutionData | null;
  events: CouncilEventItem[];
}
