/// <reference lib="webworker" />

import { generateMvpPattern } from './mvpGeneration';
import {
  createAutoGenerationSettings,
  limitAutoPalette,
  refineAutoPattern,
  removeAutoBorderBackground,
  type AutoGenerationSettings,
} from './autoPattern';
import { MARD_STANDARD_221_PALETTE } from './mardPalette';
import { drawPatternGrid, drawPatternVisual, gridCanvasDimensions } from './patternDrawing';
import { chooseGridCellPixels } from './exportSizing';
import { ALGORITHM_VERSION, type GenerationSettings, type PatternResult } from './types';
import { GenerationCancelledError } from './generation';

const workerScope: DedicatedWorkerGlobalScope = self as unknown as DedicatedWorkerGlobalScope;
const cancelledJobs = new Set<string>();
const SAMPLE_SCALE = 8;

type LocalRequest =
  | { type: 'GENERATE'; jobId: string; bitmap: ImageBitmap; settings: AutoGenerationSettings }
  | { type: 'CANCEL'; jobId: string };

type LocalResponse =
  | { type: 'PROGRESS'; jobId: string; stage: 'prepare' | 'sample' | 'map' | 'background' | 'refine' | 'render'; completed: number; total: number }
  | {
      type: 'RESULT';
      jobId: string;
      grid: PatternResult['grid'];
      cells: ArrayBuffer;
      counts: PatternResult['counts'];
      totalBeads: number;
      selectedPaletteIndices: number[];
      pattern: Blob;
      beads: Blob;
      ironed: Blob;
      metadata: {
        columns: number;
        rows: number;
        usedColors: number;
        profile: AutoGenerationSettings['profile'];
        algorithmVersion: string;
        sourceKind: AutoGenerationSettings['sourceKind'];
      };
    }
  | { type: 'ERROR'; jobId: string; message: string };

type LocalProgressStage = Extract<LocalResponse, { type: 'PROGRESS' }>['stage'];

function post(message: LocalResponse, transfer: Transferable[] = []): void {
  workerScope.postMessage(message, transfer);
}

function progress(
  jobId: string,
  stage: LocalProgressStage,
  completed: number,
  total: number,
): void {
  post({ type: 'PROGRESS', jobId, stage, completed, total });
}

function checkCancelled(jobId: string): void {
  if (cancelledJobs.has(jobId)) throw new GenerationCancelledError();
}

/** Match Perler's automatic mode: cover-fit the source into an 8px/cell raster. */
function drawSampledImage(bitmap: ImageBitmap, settings: GenerationSettings): ImageData {
  const width = settings.grid.columns * SAMPLE_SCALE;
  const height = settings.grid.rows * SAMPLE_SCALE;
  const canvas = new OffscreenCanvas(width, height);
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('无法创建离屏画布。');
  context.clearRect(0, 0, width, height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  const scale = Math.max(width / bitmap.width, height / bitmap.height)
    * Math.max(0.05, settings.transform.scale);
  const drawWidth = bitmap.width * scale;
  const drawHeight = bitmap.height * scale;
  const drawX = (width - drawWidth) / 2 + settings.transform.offsetX;
  const drawY = (height - drawHeight) / 2 + settings.transform.offsetY;
  context.drawImage(bitmap, drawX, drawY, drawWidth, drawHeight);
  return context.getImageData(0, 0, width, height);
}

async function canvasToBlob(canvas: OffscreenCanvas): Promise<Blob> {
  const blob = await canvas.convertToBlob({ type: 'image/png' });
  if (blob.type !== 'image/png' || blob.size === 0) throw new Error('PNG 渲染失败。');
  return blob;
}

async function renderGrid(result: PatternResult): Promise<Blob> {
  const cellPixels = chooseGridCellPixels(result.grid.columns, result.grid.rows);
  const dimensions = gridCanvasDimensions(result.grid.columns, result.grid.rows, cellPixels);
  const canvas = new OffscreenCanvas(dimensions.width, dimensions.height);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('无法创建图纸画布。');
  drawPatternGrid(context, {
    cells: result.cells,
    fullGrid: result.grid,
    palette: MARD_STANDARD_221_PALETTE,
    startRow: 0,
    startColumn: 0,
    rows: result.grid.rows,
    columns: result.grid.columns,
    cellPixels,
    watermarkEnabled: true,
  });
  return canvasToBlob(canvas);
}

async function renderVisual(result: PatternResult, visualMode: 'beads' | 'ironed'): Promise<Blob> {
  // Perler's automatic preview intentionally stays close to a 1040px board;
  // use the same sizing so the returned effect PNGs are interchangeable.
  const cellPixels = Math.max(1, Math.floor(1040 / Math.max(result.grid.columns, result.grid.rows)));
  const canvas = new OffscreenCanvas(result.grid.columns * cellPixels, result.grid.rows * cellPixels);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('无法创建效果图画布。');
  drawPatternVisual(context, {
    cells: result.cells,
    fullGrid: result.grid,
    palette: MARD_STANDARD_221_PALETTE,
    startRow: 0,
    startColumn: 0,
    rows: result.grid.rows,
    columns: result.grid.columns,
    cellPixels,
    visualMode,
    showGridOverlay: false,
    watermarkEnabled: false,
    includeAxes: false,
  });
  return canvasToBlob(canvas);
}

workerScope.onmessage = async (event: MessageEvent<LocalRequest>) => {
  const request = event.data;
  if (request.type === 'CANCEL') {
    cancelledJobs.add(request.jobId);
    return;
  }

  const { jobId, bitmap, settings } = request;
  cancelledJobs.delete(jobId);
  try {
    progress(jobId, 'prepare', 0, 1);
    const generationSettings = createAutoGenerationSettings(settings);
    const sampledImage = drawSampledImage(bitmap, generationSettings);
    bitmap.close();
    progress(jobId, 'prepare', 1, 1);
    const generated = generateMvpPattern(sampledImage, MARD_STANDARD_221_PALETTE, generationSettings, {
      isCancelled: () => cancelledJobs.has(jobId),
      onProgress: (update) => progress(jobId, update.stage, update.completed, Math.max(1, update.total)),
    });
    checkCancelled(jobId);
    progress(jobId, 'background', 0, 1);
    const backgroundCleaned = settings.removeBorderBackground
      ? removeAutoBorderBackground(generated)
      : generated;
    progress(jobId, 'background', 1, 1);
    checkCancelled(jobId);
    progress(jobId, 'refine', 0, 1);
    const refined = refineAutoPattern(
      limitAutoPalette(backgroundCleaned, settings.maxUsedColors),
      settings.maxUsedColors,
      settings.profile ?? 'balanced',
    );
    if (refined.counts.length === 0) {
      throw new Error('mvp 生成后没有可用拼豆格，请进入 Perler 工作台手动调整。');
    }
    progress(jobId, 'refine', 1, 1);
    checkCancelled(jobId);
    progress(jobId, 'render', 0, 3);
    const beads = await renderVisual(refined, 'beads');
    progress(jobId, 'render', 1, 3);
    checkCancelled(jobId);
    const ironed = await renderVisual(refined, 'ironed');
    progress(jobId, 'render', 2, 3);
    checkCancelled(jobId);
    const pattern = await renderGrid(refined);
    progress(jobId, 'render', 3, 3);
    const cellsBuffer = refined.cells.buffer as ArrayBuffer;
    post({
      type: 'RESULT',
      jobId,
      grid: refined.grid,
      cells: cellsBuffer,
      counts: refined.counts,
      totalBeads: refined.totalBeads,
      selectedPaletteIndices: refined.selectedPaletteIndices,
      pattern,
      beads,
      ironed,
      metadata: {
        columns: refined.grid.columns,
        rows: refined.grid.rows,
        usedColors: refined.counts.length,
        profile: settings.profile ?? 'balanced',
        algorithmVersion: ALGORITHM_VERSION,
        sourceKind: settings.sourceKind ?? 'original',
      },
    }, [cellsBuffer]);
  } catch (error) {
    bitmap?.close();
    post({
      type: 'ERROR',
      jobId,
      message: error instanceof Error ? error.message : '本地生成拼豆图纸失败。',
    });
  } finally {
    cancelledJobs.delete(jobId);
  }
};

export {};
