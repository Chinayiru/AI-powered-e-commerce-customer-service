export type Platform = 'taobao' | 'douyin'
export type Verdict = 'approve' | 'partial' | 'reject' | 'undecided'
export type SendGate = 'auto' | 'human'
export type StopReason = 'finalized' | 'budget_exhausted' | 'timeout' | 'invalid_output' | 'rejected' | 'degraded'
export type Intent = 'refund' | 'address_change' | 'shipping_urge' | 'other'
export type AftersalesType = 'refund_only' | 'return_refund'

export interface OrderItem {
  sku: string
  title: string
  qty: number
  unit_cents: number
  category: string
}

export interface ShipmentItem {
  sku: string
  qty: number
}

export interface Shipment {
  package_id: string
  carrier: string
  tracking_no: string
  shipped_at: string | null
  delivered_at: string | null
  items: ShipmentItem[]
}

export interface Order {
  order_ref: string
  status: string
  paid_cents: number
  currency: string
  created_at: string
  signed_at: string | null
  items: OrderItem[]
  shipments: Shipment[]
  platform_anomaly: boolean
}

export interface Fixture {
  platform: Platform
  stem: string
  short: string
  order_ref: string | null
  text: string
  order: Order | null
  error: string | null
}

export interface ToolCall {
  step: number
  name: string
  ok: boolean
  latency_ms: number
  error_code: string | null
  args_digest: string
}

export interface Citation {
  qa_id: string | null
  quote: string
  source: 'kb' | 'tool'
}

export interface DraftView {
  text: string
  citations: Citation[]
  risk_flags: string[]
}

export interface CaseView {
  case_id: string
  type: AftersalesType
  status: string
  amount_cents: number
  platform_refund_id: string | null
}

export interface Usage {
  input_tokens: number
  output_tokens: number
  cost_cny: number | null
  estimated: boolean
}

export interface TicketOut {
  run_id: string
  ticket_id: string
  intent: Intent
  aftersales_type: AftersalesType | null
  case: CaseView | null
  draft: DraftView
  verdict: Verdict
  send_gate: SendGate
  reason_codes: string[]
  stop_reason: StopReason
  tool_calls: ToolCall[]
  usage: Usage
  latency_ms: number
  policy_version: string
  prompt_version: string
  model: string
}

export interface RunRecord {
  run_id: string
  fixture: string
  confirm: string | null
  prompt_version: string
  policy_version: string
  recorded_at?: string
  out: TicketOut
  trace?: Record<string, unknown>
}

export interface PolicyRule {
  auto_limit_cents: number
  human_floor_cents: number
  excluded: boolean
}

export interface Policy {
  version: string
  auto_limit_cents: number
  human_floor_cents: number
  window_days: number
  window_basis: string
  max_partial_ratio: number
  per_category: Record<string, PolicyRule>
}

export interface Baseline {
  baseline: string
  created_at: string
  git_sha: string
  fixture_manifest_hash: string
  fixture_count: number
  kb_hash: string
  query_hash: string
  policy_version: string
  prompt_version: string
  llm: Record<string, unknown>
  dataset: string
  provider: string
  ac_results: Record<string, string>
  note: string
}

export interface RetrievalMiss {
  query_id: string
  query: string
  gold: string[]
  top5: string[]
}

export interface RetrievalArm {
  retriever: string
  recall_at_5: number
  n_queries: number
  n_hits: number
  unlabeled: number
  misses: RetrievalMiss[]
}

export interface Retrieval {
  dataset: string
  provider: string
  k: number
  generated_at: string
  keyword: RetrievalArm
  hybrid: RetrievalArm
  delta_pt: number
  vector_enabled: boolean
  note: string
}

export interface Meta {
  provider: string
  model: string
  prompt_version: string
  policy: Policy
  baseline: Baseline | null
  retrieval: Retrieval | null
  retrieval_threshold: number
  fixtures_count: number
  runs_count: number
  dist_ready: boolean
}

export interface RunRequestBody {
  fixture: string
  text?: string | null
  confirm?: string | null
  budget?: number
  timeout_ms?: number
  delay_ms?: number
  provider?: string | null
  client_token?: string | null
}

export interface ReplayResult {
  run_id: string
  drift: string[]
  policy_version: string
  prompt_version: string
  replayed: TicketOut
}
