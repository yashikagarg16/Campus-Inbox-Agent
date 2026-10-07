import { useEffect, useMemo, useRef } from "react";
import { type Mark, segmentText, worstStatus } from "../lib/highlight";
import { HIGHLIGHT_CLASS } from "./ui";

interface Props {
  text: string;
  marks: Mark[];
  activeKey: number | null;
  onSelect: (key: number) => void;
}

/** The email body with every evidence quote highlighted in its rule's colour. */
export function EvidenceText({ text, marks, activeKey, onSelect }: Props) {
  const segments = useMemo(() => segmentText(text, marks), [text, marks]);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeKey === null) return;
    const el = container.current?.querySelector<HTMLElement>(`[data-keys~="${activeKey}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeKey]);

  return (
    <div
      ref={container}
      className="max-h-[70vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-4 font-mono text-[13px] leading-relaxed dark:bg-slate-950"
    >
      {segments.map((seg) => {
        const status = worstStatus(seg.marks);
        if (!status) return <span key={seg.start}>{seg.text}</span>;
        const keys = seg.marks.map((m) => m.key);
        const active = activeKey !== null && keys.includes(activeKey);
        return (
          <mark
            key={seg.start}
            data-keys={keys.join(" ")}
            onClick={() => onSelect(keys[0])}
            className={`cursor-pointer rounded-sm text-inherit ${HIGHLIGHT_CLASS[status]} ${
              active ? "ring-2 ring-indigo-500" : ""
            }`}
          >
            {seg.text}
          </mark>
        );
      })}
    </div>
  );
}
