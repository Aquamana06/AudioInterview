export type Language = 'ja' | 'en' | 'de';
export type Role = 'admin' | 'operator';
export type InputMode = 'text' | 'voice' | 'system';

export interface RuntimeEnv {
  RI_db: D1Database;
  OPENAI_API_KEY?: string;
  OPENAI_TEXT_MODEL?: string;
  OPENAI_TRANSCRIBE_MODEL?: string;
}

export interface Account {
  id: string;
  role: Role;
  display_name: string;
  password_hash: string | null;
  password_salt: string | null;
  is_active: number;
  created_at: string;
  updated_at: string;
}

export interface AuthContext {
  account: Account;
  token: string;
}

export interface InterviewSession {
  id: string;
  account_id: string;
  title: string;
  language: Language;
  status: 'running' | 'ended';
  started_at: string;
  ended_at: string | null;
  updated_at: string;
}

export interface MessageRow {
  id: string;
  session_id: string;
  role: 'system' | 'user';
  content: string;
  input_mode: InputMode;
  language: Language;
  meta_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiMessage {
  id: string;
  role: 'system' | 'user';
  content: string;
  inputMode: InputMode;
  language: Language;
  createdAt: string;
  updatedAt: string;
}

export interface ExtractedInfo {
  target_work: string | null;
  situations: string[];
  practices: string[];
  reasons: string[];
  values: string[];
  sources: string[];
  personal_meanings: string[];
  irregular_situations: string[];
  irregular_responses: string[];
  persona_notes: string[];
  emotions: string[];
  user_questions: string[];
  signs_of_friction: string[];
  signs_of_resistance: string[];
  signs_of_no_information: string[];
  wants_to_stop: boolean;
}

export interface InterviewState {
  target_work: string | null;
  task_coverage: number;
  task_depth: number;
  irregular_coverage: number;
  rapport: number;
  known_facts: string[];
  asked_points: string[];
  persona_notes: string[];
  consecutive_questions: number;
  turns_since_reflection: number;
  friction_count: number;
  resistance_count: number;
  turn_count: number;
}

export interface ConversationGuide {
  should_ask_question: boolean;
  should_end: boolean;
  should_repair?: boolean;
  should_answer_user_question?: boolean;
  guidance: string;
  priorities: string[];
  dice_hint?: 'C' | 'D' | 'E' | 'I';
  avoid_reasking: string[];
  use_as_known: string[];
}

export interface AgentResult {
  text: string;
  state: InterviewState;
  stateLabel: 'running' | 'end';
  extracted: ExtractedInfo;
  guide: ConversationGuide;
}
