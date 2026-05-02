import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

type Props = {
  lang: string;
  text: string;
};

export default function CodeBlock({ lang, text }: Props) {
  return (
    <SyntaxHighlighter
      style={oneDark}
      language={lang}
      PreTag="div"
      customStyle={{
        margin: 0,
        borderRadius: "0.5rem",
        fontSize: "0.875rem",
      }}
    >
      {text}
    </SyntaxHighlighter>
  );
}
