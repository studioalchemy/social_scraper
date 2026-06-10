"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Settings {
  accounts: string[];
  recipient_emails: string[];
  business_problems: string[];
  schedule_days: number;
}

interface Status {
  running: boolean;
  last_run: string | null;
  last_error: string | null;
  status: "idle" | "running" | "success" | "error";
}

/* ── Icons ──────────────────────────────────────────────────────────────── */

function IconX(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" {...props}>
      <path d="M6 6 18 18 M18 6 6 18" />
    </svg>
  );
}
function IconPlay(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" {...props}>
      <path d="M7 4.5v15l13-7.5z" />
    </svg>
  );
}
function IconCheck(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M5 12 10 17 19 7" />
    </svg>
  );
}
function IconPlus(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" {...props}>
      <path d="M12 5v14 M5 12h14" />
    </svg>
  );
}
function IconAlert(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v5" />
      <path d="M12 16h.01" />
    </svg>
  );
}

/* ── Pieces ─────────────────────────────────────────────────────────────── */

function Tag({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="tag">
      {label}
      <button onClick={onRemove} aria-label={`Remove ${label}`}>
        <IconX />
      </button>
    </span>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      color: "var(--ink-muted)",
      fontSize: 13,
      fontWeight: 500,
      marginBottom: 10,
    }}>
      {children}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export default function Home() {
  const [settings, setSettings] = useState<Settings>({
    accounts: [],
    recipient_emails: [],
    business_problems: [],
    schedule_days: 7,
  });
  const [status, setStatus] = useState<Status>({
    running: false,
    last_run: null,
    last_error: null,
    status: "idle",
  });
  const [accountInput, setAccountInput] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [bpInput, setBpInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchSettings = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/settings`);
      if (res.ok) setSettings(await res.json());
    } catch { /* backend not reachable yet */ }
    finally { setLoading(false); }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/status`);
      if (res.ok) setStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchSettings();
    fetchStatus();
  }, [fetchSettings, fetchStatus]);

  useEffect(() => {
    if (status.running) {
      pollRef.current = setInterval(fetchStatus, 3000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status.running, fetchStatus]);

  const addAccount = () => {
    const v = accountInput.trim().replace(/^@/, "").toLowerCase();
    if (!v || settings.accounts.includes(v)) return;
    setSettings((s) => ({ ...s, accounts: [...s.accounts, v] }));
    setAccountInput("");
  };
  const removeAccount = (a: string) =>
    setSettings((s) => ({ ...s, accounts: s.accounts.filter((x) => x !== a) }));

  const addEmail = () => {
    const v = emailInput.trim().toLowerCase();
    if (!v || !v.includes("@") || settings.recipient_emails.includes(v)) return;
    setSettings((s) => ({ ...s, recipient_emails: [...s.recipient_emails, v] }));
    setEmailInput("");
  };
  const removeEmail = (e: string) =>
    setSettings((s) => ({
      ...s,
      recipient_emails: s.recipient_emails.filter((x) => x !== e),
    }));

  const addBp = () => {
    const v = bpInput.trim();
    if (!v || settings.business_problems.includes(v)) return;
    if (settings.business_problems.length >= 3) return;
    setSettings((s) => ({ ...s, business_problems: [...s.business_problems, v] }));
    setBpInput("");
  };
  const removeBp = (p: string) =>
    setSettings((s) => ({
      ...s,
      business_problems: s.business_problems.filter((x) => x !== p),
    }));

  const handleKeyDown =
    (fn: () => void) => (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") fn();
    };

  const saveSettings = async () => {
    const ok = window.confirm(
      `Save these settings?\n\n` +
      `• ${settings.accounts.length} account${settings.accounts.length === 1 ? "" : "s"}\n` +
      `• ${settings.recipient_emails.length} recipient${settings.recipient_emails.length === 1 ? "" : "s"}\n` +
      `• ${settings.business_problems.length} business problem${settings.business_problems.length === 1 ? "" : "s"}\n` +
      `• Every ${settings.schedule_days} ${settings.schedule_days === 1 ? "day" : "days"}`
    );
    if (!ok) return;

    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        setSaveMsg("Settings updated");
      } else {
        const err = await res.json();
        setSaveMsg(`Error: ${err.detail ?? "unknown error"}`);
      }
    } catch {
      setSaveMsg("Could not reach backend");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3500);
    }
  };

  const runNow = async () => {
    try {
      const res = await fetch(`${API}/api/run`, { method: "POST" });
      if (res.ok) {
        setStatus((s) => ({ ...s, running: true, status: "running" }));
        fetchStatus();
      } else {
        const err = await res.json();
        alert(err.detail ?? "Failed to start run.");
      }
    } catch {
      alert("Could not reach backend");
    }
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "Never";
    return new Intl.DateTimeFormat("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  };

  const statusMeta =
    status.status === "running"
      ? { color: "var(--warn)",     label: "Running" }
      : status.status === "success"
      ? { color: "var(--success)",  label: "Last run succeeded" }
      : status.status === "error"
      ? { color: "var(--danger)",   label: "Last run failed" }
      : { color: "var(--ink-muted)", label: "Idle" };

  if (loading) {
    return (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        minHeight: "100dvh",
      }}>
        <div className="spin" style={{
          width: 22, height: 22, borderRadius: "50%",
          border: "2px solid rgba(255,255,255,0.15)",
          borderTopColor: "rgba(255,255,255,0.95)",
        }} />
      </div>
    );
  }

  const fillPct = ((settings.schedule_days - 1) / 29) * 100;

  return (
    <main style={{
      maxWidth: 980,
      margin: "0 auto",
      padding: "72px 24px 160px",
    }}>
      {/* Hero header */}
      <header className="rise rise-1" style={{ marginBottom: 56 }}>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 18,
          flexWrap: "wrap",
        }}>
          <Eyebrow>Trend Agent</Eyebrow>
          <div style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            color: "var(--ink-soft)",
            fontSize: 13,
            fontWeight: 500,
          }}>
            <span className={status.status === "running" ? "pulse-dot" : ""}
              style={{
                width: 8, height: 8, borderRadius: "50%",
                background: statusMeta.color,
                display: "inline-block",
                position: "relative",
              }}
            />
            {statusMeta.label}
          </div>
        </div>

        <h1 className="display" style={{
          fontSize: "clamp(3rem, 7.5vw, 5.4rem)",
          color: "var(--ink-bright)",
          marginBottom: 18,
        }}>
          Watch competitors.<br />
          Get a report.
        </h1>
        <p style={{
          color: "var(--ink-soft)",
          fontSize: "clamp(1.05rem, 1.4vw, 1.2rem)",
          fontWeight: 400,
          lineHeight: 1.45,
          maxWidth: "60ch",
          letterSpacing: "-0.01em",
        }}>
          A written analysis and the top-performing posts from a set of Instagram accounts, emailed to you on the cadence you set.
        </p>
      </header>

      {/* Error banner */}
      {status.last_error && (
        <div className="surface rise rise-2" style={{
          padding: "18px 22px",
          marginBottom: 28,
          display: "flex",
          alignItems: "flex-start",
          gap: 14,
          background: "rgba(255, 69, 58, 0.10)",
          border: "1px solid rgba(255, 69, 58, 0.30)",
        }}>
          <span style={{
            color: "var(--danger)",
            marginTop: 2,
            flexShrink: 0,
          }}>
            <IconAlert />
          </span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{
              color: "var(--ink-bright)",
              fontSize: 15,
              fontWeight: 600,
              marginBottom: 4,
            }}>
              Last run failed
            </div>
            <div style={{
              color: "var(--ink-soft)",
              fontSize: 14,
              wordBreak: "break-word",
            }}>
              {status.last_error}
            </div>
          </div>
        </div>
      )}

      {/* Cadence hero card */}
      <section className="surface rise rise-2" style={{
        padding: "40px 44px",
        marginBottom: 24,
      }}>
        <Eyebrow>Cadence</Eyebrow>

        <div style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) auto",
          gap: 32,
          alignItems: "end",
          marginBottom: 28,
        }}>
          <div>
            <div className="display" style={{
              fontSize: "clamp(2.2rem, 5vw, 3.4rem)",
              color: "var(--ink-bright)",
            }}>
              Every {settings.schedule_days} {settings.schedule_days === 1 ? "day" : "days"}
            </div>
            <div style={{
              color: "var(--ink-soft)",
              fontSize: 14.5,
              marginTop: 10,
            }}>
              Last run · {formatDate(status.last_run)}
            </div>
          </div>

          <div style={{
            fontSize: "clamp(70px, 11vw, 124px)",
            lineHeight: 0.85,
            fontWeight: 200,
            color: "var(--ink-bright)",
            letterSpacing: "-0.07em",
            textAlign: "right",
            minWidth: 100,
            fontVariantNumeric: "tabular-nums",
          }}>
            {settings.schedule_days}
          </div>
        </div>

        <input
          type="range"
          min={1}
          max={30}
          value={settings.schedule_days}
          onChange={(e) =>
            setSettings((s) => ({ ...s, schedule_days: Number(e.target.value) }))
          }
          className="slider"
          style={{ "--fill": `${fillPct}%` } as React.CSSProperties}
          aria-label="Schedule frequency in days"
        />
        <div style={{
          display: "flex", justifyContent: "space-between",
          color: "var(--ink-muted)", fontSize: 12.5, marginTop: 12,
          fontWeight: 500,
        }}>
          <span>Daily</span>
          <span>Weekly</span>
          <span>Monthly</span>
        </div>
      </section>

      {/* Two-col forms */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 22,
        marginBottom: 36,
      }}>
        <section className="surface rise rise-3" style={{ padding: "32px 32px" }}>
          <h2 className="display" style={{
            fontSize: 24,
            color: "var(--ink-bright)",
            marginBottom: 6,
          }}>
            Accounts
          </h2>
          <p style={{ color: "var(--ink-soft)", fontSize: 14, marginBottom: 22 }}>
            Instagram handles to watch. No @ needed.
          </p>

          <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
            <input
              className="input-field"
              placeholder="nike"
              value={accountInput}
              onChange={(e) => setAccountInput(e.target.value)}
              onKeyDown={handleKeyDown(addAccount)}
            />
            <button onClick={addAccount} className="btn btn-ghost" aria-label="Add account">
              <IconPlus /> Add
            </button>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, minHeight: 36 }}>
            {settings.accounts.length === 0 ? (
              <span style={{ color: "var(--ink-muted)", fontSize: 14 }}>
                No accounts yet
              </span>
            ) : (
              settings.accounts.map((a) => (
                <Tag key={a} label={`@${a}`} onRemove={() => removeAccount(a)} />
              ))
            )}
          </div>
        </section>

        <section className="surface rise rise-4" style={{ padding: "32px 32px" }}>
          <h2 className="display" style={{
            fontSize: 24,
            color: "var(--ink-bright)",
            marginBottom: 6,
          }}>
            Recipients
          </h2>
          <p style={{ color: "var(--ink-soft)", fontSize: 14, marginBottom: 22 }}>
            Where the report email lands.
          </p>

          <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
            <input
              className="input-field"
              placeholder="team@company.com"
              type="email"
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              onKeyDown={handleKeyDown(addEmail)}
            />
            <button onClick={addEmail} className="btn btn-ghost" aria-label="Add recipient">
              <IconPlus /> Add
            </button>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, minHeight: 36 }}>
            {settings.recipient_emails.length === 0 ? (
              <span style={{ color: "var(--ink-muted)", fontSize: 14 }}>
                No recipients yet
              </span>
            ) : (
              settings.recipient_emails.map((e) => (
                <Tag key={e} label={e} onRemove={() => removeEmail(e)} />
              ))
            )}
          </div>
        </section>
      </div>

      {/* Business problems card */}
      <section className="surface rise rise-5" style={{ padding: "32px 32px", marginBottom: 36 }}>
        <h2 className="display" style={{
          fontSize: 24,
          color: "var(--ink-bright)",
          marginBottom: 6,
        }}>
          Business problems
        </h2>
        <p style={{ color: "var(--ink-soft)", fontSize: 14, marginBottom: 22 }}>
          One to three problems the brand is trying to solve on Instagram. Each section of the report is anchored to these.
        </p>

        <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
          <input
            className="input-field"
            placeholder="e.g. increase purchase frequency"
            value={bpInput}
            onChange={(e) => setBpInput(e.target.value)}
            onKeyDown={handleKeyDown(addBp)}
            disabled={settings.business_problems.length >= 3}
          />
          <button
            onClick={addBp}
            disabled={settings.business_problems.length >= 3}
            className="btn btn-ghost"
            aria-label="Add business problem"
          >
            <IconPlus /> Add
          </button>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, minHeight: 36 }}>
          {settings.business_problems.length === 0 ? (
            <span style={{ color: "var(--ink-muted)", fontSize: 14 }}>
              No business problems yet
            </span>
          ) : (
            settings.business_problems.map((p) => (
              <Tag key={p} label={p} onRemove={() => removeBp(p)} />
            ))
          )}
        </div>
        {settings.business_problems.length >= 3 && (
          <div style={{ color: "var(--ink-muted)", fontSize: 12, marginTop: 10 }}>
            Maximum of 3 business problems.
          </div>
        )}
      </section>

      {/* Hint line */}
      <div className="rise rise-5" style={{
        color: "var(--ink-muted)",
        fontSize: 13,
        textAlign: "center",
        marginBottom: 4,
      }}>
        <strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>Save settings</strong> stores changes and updates the schedule.{" "}
        <strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>Run now</strong> generates a report and emails it immediately.
      </div>

      {/* Floating action dock */}
      <div className="dock-wrap">
        <div className="dock rise rise-6">
          {saveMsg && (
            <span className="dock-msg" style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              color: saveMsg.startsWith("Error") || saveMsg.startsWith("Could")
                ? "var(--danger)"
                : "var(--success)",
              fontSize: 13.5,
              fontWeight: 500,
            }}>
              {!saveMsg.startsWith("Error") && !saveMsg.startsWith("Could") && <IconCheck />}
              {saveMsg}
            </span>
          )}

          <button onClick={saveSettings} disabled={saving} className="btn btn-ghost">
            {saving ? (
              <>
                <span className="spin" style={{
                  display: "inline-block",
                  width: 12, height: 12, borderRadius: "50%",
                  border: "1.5px solid rgba(255,255,255,0.3)",
                  borderTopColor: "rgba(255,255,255,0.95)",
                }} />
                Saving
              </>
            ) : (
              <>Save settings</>
            )}
          </button>
          <button
            onClick={runNow}
            disabled={status.running}
            className="btn btn-primary"
          >
            {status.running ? (
              <>
                <span className="spin" style={{
                  display: "inline-block",
                  width: 12, height: 12, borderRadius: "50%",
                  border: "1.5px solid rgba(0,0,0,0.2)",
                  borderTopColor: "#000",
                }} />
                Running
              </>
            ) : (
              <>
                <IconPlay /> Run now
              </>
            )}
          </button>
        </div>
      </div>
    </main>
  );
}
