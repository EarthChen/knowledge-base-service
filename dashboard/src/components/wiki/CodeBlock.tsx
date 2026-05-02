import SharedCodeBlock from "../CodeBlock";

type Props = {
  lang: string;
  text: string;
};

export default function CodeBlock({ lang, text }: Props) {
  return <SharedCodeBlock code={text} language={lang} />;
}
