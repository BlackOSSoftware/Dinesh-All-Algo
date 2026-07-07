export async function withLock<T>(_key: string, fn: () => Promise<T> | T): Promise<T> {
  return fn();
}
