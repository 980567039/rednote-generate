/** Error used to abort a local browser generation job. */
export class GenerationCancelledError extends Error {
  constructor() {
    super('任务已取消。');
    this.name = 'GenerationCancelledError';
  }
}
