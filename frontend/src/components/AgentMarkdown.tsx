import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import "./AgentMarkdown.css";

/** Model output is untrusted: keep HTML disabled and images as explicit links. */
export function AgentMarkdown({ content }: { content: string }) {
  return <div className="agent-markdown">
    <Markdown skipHtml remarkPlugins={[remarkGfm]} components={{
      h1: ({ children }) => <h3>{children}</h3>,
      h2: ({ children }) => <h3>{children}</h3>,
      h3: ({ children }) => <h4>{children}</h4>,
      a: ({ href, children }) => href
        ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
        : <span>{children}</span>,
      img: ({ src, alt }) => src
        ? <a href={src} target="_blank" rel="noopener noreferrer">图片：{alt || "查看图片"}</a>
        : <span>{alt || "图片链接不可用"}</span>,
      table: ({ children }) => <div className="agent-markdown-table" tabIndex={0} aria-label="回答中的表格"><table>{children}</table></div>,
    }}>{content}</Markdown>
  </div>;
}
