export interface TranscriptionOptions {
  bpm: number;
  tuning: string;
  capo: number;
  max_fret: number;
  max_fret_span: number;
  min_duration_seconds: number;
  min_velocity: number;
}

export interface GuitarEvent {
  start: number;
  end: number;
  start_beat: number;
  duration_beats: number;
  pitch: number;
  pitch_name: string;
  velocity: number;
  string: number;
  fret: number;
}

export interface TranscriptionResult {
  title: string;
  bpm: number;
  tuning: string;
  capo: number;
  max_fret: number;
  note_count: number;
  raw_note_count: number;
  events: GuitarEvent[];
  warnings: string[];
  tab_text: string;
  artifacts: Record<"midi" | "musicxml" | "tab" | "json", string>;
}

export interface JobBase {
  id: string;
  filename: string;
  progress: number;
  stage: string;
  message: string;
  created_at: string;
  updated_at: string;
  options: TranscriptionOptions;
  error: string | null;
  revision: number;
}

export interface TranscriptionJob extends JobBase {
  status: "queued" | "running" | "succeeded" | "failed";
  result: TranscriptionResult | null;
}

export interface GuitarPart {
  key: "lead" | "rhythm";
  label: string;
  audio_format: string;
  transcription: TranscriptionResult | null;
  error: string | null;
}

export interface SongTranscriptionResult {
  title: string;
  bpm: number;
  source: string;
  guitars: GuitarPart[];
  backing_available: boolean;
  warnings: string[];
  score_artifact: string | null;
}

export interface SongTranscriptionJob extends JobBase {
  status: "queued" | "running" | "succeeded" | "partial" | "failed";
  result: SongTranscriptionResult | null;
}

export type SeparationQuality = "fast" | "balanced" | "best";

export interface SeparationStemDefinition {
  key: string;
  label: string;
}

export interface SeparationModel {
  key: string;
  label: string;
  description: string;
  stems: SeparationStemDefinition[];
  memory_hint: string;
}

export interface SeparationOptions {
  model: string;
  remove_stems: string[];
  quality: SeparationQuality;
}

export interface SeparationStem {
  key: string;
  label: string;
  filename: string;
  audio_format: string;
}

export interface Accompaniment {
  key: string;
  label: string;
  removed_stem: string;
  removed_label: string;
  filename: string;
  audio_format: string;
}

export interface SeparationResult {
  title: string;
  model: {
    key: string;
    label: string;
  };
  device: string;
  quality: SeparationQuality;
  duration_seconds: number | null;
  stems: SeparationStem[];
  accompaniments: Accompaniment[];
  warnings: string[];
  archive_filename: string | null;
}

export interface SeparationJob {
  id: string;
  filename: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  stage: string;
  message: string;
  created_at: string;
  updated_at: string;
  options: SeparationOptions;
  result: SeparationResult | null;
  error: string | null;
  revision: number;
}

export interface RecentJobSummary {
  id: string;
  mode: "guitar" | "song" | "separate";
  filename: string;
  status: string;
  progress: number;
  message: string;
  updated_at: string;
  result_title: string | null;
}

export interface RecentJobsResponse {
  jobs: RecentJobSummary[];
}

export interface MarketSuggestion {
  id: string;
  title: string;
  artist: string;
  album: string;
  kind: string;
  url: string;
  preview_url: string | null;
  artwork_url: string | null;
  relevance: number;
}

export interface MarketSearchResponse {
  provider: string;
  queries: string[];
  suggestions: MarketSuggestion[];
}

export interface ScoreSuggestion {
  id: string;
  title: string;
  artist: string;
  type: string;
  version: string;
  rating: number;
  votes: number;
  url: string;
  provider: string;
  meta: string;
}

export interface ScoreLibrary {
  name: string;
  url: string;
}

export interface ScoreSearchResponse {
  provider: string;
  query: string;
  suggestions: ScoreSuggestion[];
  libraries: ScoreLibrary[];
}

export interface Health {
  status: string;
  python: string;
  transcription_ready: boolean;
  cloud_separation_ready: boolean;
  cloud_separation_model: string;
  local_separation_ready: boolean;
  separation_device: string | null;
  separation_models: SeparationModel[];
  supported_formats: string[];
  max_upload_mb: number;
}

