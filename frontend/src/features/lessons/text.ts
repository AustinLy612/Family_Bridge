/** Text helpers for the lesson screens. */

/**
 * The model often ends its message with the same question it also returns separately. Show the
 * question once (D92): taken off the end of the message and set in bold, or not repeated at all
 * when it sits inside the message.
 */
export function splitQuestion(content: string, question: string | null): [string, string | null] {
  const q = question?.trim();
  if (!q) return [content, null];
  const body = content.trimEnd();
  if (body.endsWith(q)) return [body.slice(0, body.length - q.length).trimEnd(), q];
  if (body.includes(q)) return [content, null];
  return [content, q];
}
