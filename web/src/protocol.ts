export const MAX_PROMPT_LENGTH = 100_000;
export const MAX_NAMES_LENGTH = 10_000;
export const PREVIEW_LENGTH = 20_000;
export const PREVIEW_MAPPINGS = 100;

export interface VaultMapping {
  type: string;
  surrogate: string;
  original: string;
}

export interface MaskResult {
  masked: string;
  mappings: VaultMapping[];
}

export type Request =
  | { id: number; kind: "mask"; manifestUrl: string; prompt: string; names: string }
  | { id: number; kind: "restore"; chunks: string[] };

export type Reply =
  | { id: number; kind: "status"; message: string }
  | { id: number; kind: "error"; message: string }
  | { id: number; kind: "masked"; result: MaskResult }
  | { id: number; kind: "restored"; chunks: string[] };
