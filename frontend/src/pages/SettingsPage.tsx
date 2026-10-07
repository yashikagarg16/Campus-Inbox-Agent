import { useState, type FormEvent } from "react";
import { getApiUrl, getToken, saveConnection } from "../api";
import { useServerConfig } from "../App";
import { Button, Card, ErrorBox, Field, inputClass, Notice } from "../components/ui";

export function SettingsPage() {
  const { config, error, reload } = useServerConfig();
  const [apiUrl, setApiUrl] = useState(getApiUrl());
  const [token, setToken] = useState(getToken());
  const [saved, setSaved] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    saveConnection(apiUrl, token);
    setSaved(true);
    await reload();
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Backend URL">
            <input className={inputClass} value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} />
          </Field>
          <Field label="Access token" hint="Only needed if the server sets APP_TOKEN. Stored in this browser only.">
            <input className={inputClass} type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          </Field>
          <Button type="submit">Save and reconnect</Button>
        </form>
      </Card>
      {saved && !error && config && <Notice tone="ok">Connected.</Notice>}
      <ErrorBox error={error} />
      {config && (
        <Card>
          <h2 className="mb-2 font-semibold">Server</h2>
          <ul className="space-y-1 text-sm">
            <li>LLM (Gemini): {config.llm_configured ? "configured" : "not configured: set GEMINI_API_KEY"}</li>
            <li>
              Inbox sync (read-only):{" "}
              {config.mail_source === "graph" ? "Outlook / Microsoft 365" : config.imap_configured ? "IMAP" : "not configured"}
            </li>
            <li>Access token required: {config.auth_required ? "yes" : "no"}</li>
          </ul>
        </Card>
      )}
    </div>
  );
}
