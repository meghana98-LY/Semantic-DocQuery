import SourceCards from "./SourceCards";
import RedactedText from "./RedactedText";

// Renders a structured assistant response: answer paragraph + source cards below it.
export default function AssistantContent({ content, sources, query }) {
  return (
    <>
      <p className="message-content">
        <RedactedText text={content} />
      </p>
      {sources && sources.length > 0 && (
        <SourceCards sources={sources} query={query} />
      )}
    </>
  );
}
