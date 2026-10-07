import { useState } from "react";
import { api, type AuditEvent } from "../api";
import { formatDateTime } from "../lib/format";
import { Button, ErrorBox } from "./ui";

export function AuditLog({ opportunityId }: { opportunityId: number }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState(false);

  async function toggle() {
    if (!open && events === null) {
      try {
        setEvents(await api.getAudit(opportunityId));
      } catch (e) {
        setError(e);
      }
    }
    setOpen(!open);
  }

  return (
    <div className="space-y-2">
      <Button variant="secondary" onClick={toggle} aria-expanded={open}>
        {open ? "Hide audit log" : "Show audit log"}
      </Button>
      <ErrorBox error={error} />
      {open && events && (
        <ol className="space-y-1 text-sm">
          {events.map((e) => (
            <li key={e.id} className="rounded-md p-2 ring-1 ring-slate-200 dark:ring-slate-800">
              <details>
                <summary className="cursor-pointer">
                  <span className="font-mono text-xs text-slate-500">{formatDateTime(e.created_at)}</span>{" "}
                  <span className="font-medium">{e.event.replaceAll("_", " ")}</span>
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-600 dark:text-slate-400">
                  {JSON.stringify(e.detail, null, 2)}
                </pre>
              </details>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
