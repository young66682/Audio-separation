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

export interface Health {
  status: string;
  python: string;
  transcription_ready: boolean;
  cloud_separation_ready: boolean;
  cloud_separation_model: string;
  supported_formats: string[];
  max_upload_mb: number;
}

