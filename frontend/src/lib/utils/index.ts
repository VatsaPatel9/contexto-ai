import { v4 as uuidv4 } from 'uuid';

export function generateId(): string {
  return uuidv4();
}

/**
 * Auto-generate a chat title from the first user message.
 */
export function generateTitle(content: string): string {
  const trimmed = content.trim();
  if (trimmed.length <= 50) return trimmed;
  return trimmed.slice(0, 47) + '...';
}

/**
 * Scroll an element to the bottom smoothly.
 */
export function scrollToBottom(el: HTMLElement, smooth = true) {
  el.scrollTo({
    top: el.scrollHeight,
    behavior: smooth ? 'smooth' : 'instant'
  });
}

/**
 * Copy text to clipboard.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * Format a timestamp for display.
 */
export function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
