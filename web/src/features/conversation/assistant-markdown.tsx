import { memo } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Model text is lower-trust content. No relative routes, executable URLs, raw
// HTML or auto-loaded images belong in an assistant answer.
export function safeLink(url: string): string {
  try {
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.hostname === 'localhost' ||
        parsed.hostname.endsWith('.localhost') || parsed.hostname.endsWith('.local') ||
        /^\d+\.\d+\.\d+\.\d+$/.test(parsed.hostname) ||
        parsed.hostname.startsWith('[')) return '';
    return parsed.href;
  } catch {
    return '';
  }
}

const markdownPlugins = [remarkGfm];
const markdownComponents: Components = {
  a: ({ href, children }) => href ?
    <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> :
    <span>{children}</span>,
  img: ({ alt }) => <span className="markdown-image-alt">{alt || 'Image'} (image not loaded)</span>,
  pre: ({ children }) => <pre tabIndex={0}>{children}</pre>,
  table: ({ children }) => <div className="markdown-table-scroll" role="region"
    aria-label="Answer table" tabIndex={0}><table>{children}</table></div>,
};

export const AssistantMarkdown = memo(function AssistantMarkdown({ text }: { text: string }) {
  return <div className="assistant-markdown">
    <ReactMarkdown skipHtml remarkPlugins={markdownPlugins} urlTransform={safeLink} components={markdownComponents}>{text}</ReactMarkdown>
  </div>;
});
