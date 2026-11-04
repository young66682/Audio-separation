import type {
  Health,
  SeparationJob,
  SeparationOptions,
  SongTranscriptionJob,
  TranscriptionJob,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

async function readError(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    return payload.detail ?? `请求失败 (${response.status})`;
  } catch {
    return `请求失败 (${response.status})`;
  }
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch(`${API_BASE}/api/health`);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

export async function createTranscription(
  file: File,
  options: {
    bpm: number;
    tuning: string;
    capo: number;
    maxFret: number;
    maxFretSpan: number;
    minDuration: number;
    minVelocity: number;
  },
): Promise<{ job_id: string }> {
  const body = new FormData();
  body.append("audio", file);
  body.append("bpm", String(options.bpm));
  body.append("tuning", options.tuning);
  body.append("capo", String(options.capo));
  body.append("max_fret", String(options.maxFret));
  body.append("max_fret_span", String(options.maxFretSpan));
  body.append("min_duration_seconds", String(options.minDuration));
  body.append("min_velocity", String(options.minVelocity));

  const response = await fetch(`${API_BASE}/api/transcriptions`, {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

export async function createSongTranscription(
  file: File,
  options: {
    bpm: number;
    tuning: string;
    capo: number;
    maxFret: number;
    maxFretSpan: number;
    minDuration: number;
    minVelocity: number;
  },
): Promise<{ job_id: string }> {
  const body = new FormData();
  body.append("audio", file);
  body.append("bpm", String(options.bpm));
  body.append("tuning", options.tuning);
  body.append("capo", String(options.capo));
  body.append("max_fret", String(options.maxFret));
  body.append("max_fret_span", String(options.maxFretSpan));
  body.append("min_duration_seconds", String(options.minDuration));
  body.append("min_velocity", String(options.minVelocity));

  const response = await fetch(`${API_BASE}/api/song-transcriptions`, {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

export async function createSeparation(
  file: File,
  options: SeparationOptions,
): Promise<{ job_id: string }> {
  const body = new FormData();
  body.append("audio", file);
  body.append("model", options.model);
  body.append("remove_stems", options.remove_stems.join(","));
  body.append("quality", options.quality);

  const response = await fetch(`${API_BASE}/api/separations`, {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

export function jobEndpoint(jobId: string, suffix = ""): string {
  return `${API_BASE}/api/transcriptions/${jobId}${suffix}`;
}

export function artifactUrl(jobId: string, artifact: string): string {
  return jobEndpoint(jobId, `/artifacts/${artifact}`);
}

export function audioUrl(jobId: string): string {
  return jobEndpoint(jobId, "/audio");
}

export function songEndpoint(jobId: string, suffix = ""): string {
  return `${API_BASE}/api/song-transcriptions/${jobId}${suffix}`;
}

export function songAudioUrl(jobId: string, stem: "original" | "lead" | "rhythm" | "backing"): string {
  return songEndpoint(jobId, `/audio/${stem}`);
}

export function songArtifactUrl(jobId: string, guitar: "lead" | "rhythm", artifact: string): string {
  return songEndpoint(jobId, `/guitars/${guitar}/artifacts/${artifact}`);
}

export function songArchiveUrl(jobId: string): string {
  return songEndpoint(jobId, "/archive");
}

export function songScoreUrl(jobId: string): string {
  return songEndpoint(jobId, "/score");
}

export function separationEndpoint(jobId: string, suffix = ""): string {
  return `${API_BASE}/api/separations/${jobId}${suffix}`;
}

export function separationSourceAudioUrl(jobId: string): string {
  return separationEndpoint(jobId, "/audio/source");
}

export function separationAudioUrl(
  jobId: string,
  kind: "stem" | "accompaniment",
  stem: string,
): string {
  return separationEndpoint(jobId, `/audio/${kind}/${stem}`);
}

export function separationArchiveUrl(jobId: string): string {
  return separationEndpoint(jobId, "/archive");
}

export function subscribeToJob(
  jobId: string,
  onJob: (job: TranscriptionJob) => void,
  onDone: () => void,
  onError: (message: string) => void,
): () => void {
  const source = new EventSource(jobEndpoint(jobId, "/events"));
  const handleProgress = (event: MessageEvent<string>) => {
    onJob(JSON.parse(event.data) as TranscriptionJob);
  };
  source.addEventListener("progress", handleProgress as EventListener);
  source.addEventListener("done", onDone);
  source.addEventListener("error", () => {
    if (source.readyState === EventSource.CLOSED) {
      onError("实时进度连接已断开");
    }
  });
  return () => source.close();
}

export function subscribeToSongJob(
  jobId: string,
  onJob: (job: SongTranscriptionJob) => void,
  onDone: () => void,
  onError: (message: string) => void,
): () => void {
  const source = new EventSource(songEndpoint(jobId, "/events"));
  const handleProgress = (event: MessageEvent<string>) => {
    onJob(JSON.parse(event.data) as SongTranscriptionJob);
  };
  source.addEventListener("progress", handleProgress as EventListener);
  source.addEventListener("done", onDone);
  source.addEventListener("error", () => {
    if (source.readyState === EventSource.CLOSED) {
      onError("实时进度连接已断开");
    }
  });
  return () => source.close();
}

export function subscribeToSeparationJob(
  jobId: string,
  onJob: (job: SeparationJob) => void,
  onDone: () => void,
  onError: (message: string) => void,
): () => void {
  const source = new EventSource(separationEndpoint(jobId, "/events"));
  const handleProgress = (event: MessageEvent<string>) => {
    onJob(JSON.parse(event.data) as SeparationJob);
  };
  source.addEventListener("progress", handleProgress as EventListener);
  source.addEventListener("done", onDone);
  source.addEventListener("error", () => {
    if (source.readyState === EventSource.CLOSED) {
      onError("实时进度连接已断开");
    }
  });
  return () => source.close();
}

