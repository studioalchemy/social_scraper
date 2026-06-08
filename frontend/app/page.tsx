"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Settings {
  accounts: string[];
  recipient_emails: string[];
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
    <span className="tag-glass">
      {label}
      <button onClick={onRemove} aria-label={`Remove ${label}`}>
        <IconX />
      </button>
    </span>
  );
}

function GlassCard({
  children,
  className = "",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <section className={`glass ${className}`} style={{ padding: 26, ...style }}>
      {children}
    </section>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      color: "var(--ink-muted)",
      fontSize: 12,
      fontWeight: 500,
      marginBottom: 8,
      letterSpacing: 0.1,
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

  const handleKeyDown =
    (fn: () => void) => (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") fn();
    };

  const saveSettings = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        setSaveMsg("Saved");
      } else {
        const err = await res.json();
        setSaveMsg(`Error: ${err.detail ?? "unknown error"}`);
      }
    } catch {
      setSaveMsg("Could not reach backend");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3000);
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
      ? { color: "var(--warn)",   label: "Running" }
      : status.status === "success"
      ? { color: "var(--success)", label: "Last run succeeded" }
      : status.status === "error"
      ? { color: "var(--danger)",  label: "Last run failed" }
      : { color: "var(--ink-muted)", label: "Idle" };

  if (loading) {
    return (
      <>
        <div className="grain" />
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          minHeight: "100dvh",
        }}>
          <div className="glass" style={{
            padding: "28px 40px", display: "flex", alignItems: "center", gap: 14,
          }}>
            <div className="spin" style={{
              width: 16, height: 16, borderRadius: "50%",
              border: "2px solid rgba(255,255,255,0.18)",
              borderTopColor: "rgba(255,255,255,0.95)",
            }} />
            <span style={{ color: "var(--ink-soft)" }}>Loading</span>
          </div>
        </div>
      </>
    );
  }

  const fillPct = ((settings.schedule_days - 1) / 29) * 100;

  return (
    <>
      <div className="grain" />

      <main style={{
        maxWidth: 920,
        margin: "0 auto",
        padding: "56px 22px 160px",
      }}>
        {/* Header */}
        <header className="rise rise-1" style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 32,
          flexWrap: "wrap",
        }}>
          <div>
            <h1 style={{
              fontSize: "clamp(2.1rem, 4.8vw, 3rem)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.05,
              color: "var(--ink-bright)",
            }}>
              Instagram trend agent
            </h1>
            <p style={{
              color: "var(--ink-soft)",
              marginTop: 10,
              fontSize: 14.5,
              maxWidth: "62ch",
            }}>
              Watch a set of competitors. A written report and the top posts get emailed to you on the cadence you set.
            </p>
          </div>

          <div className="glass" style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "9px 16px",
            borderRadius: "var(--radius-pill)",
          }}>
            <span className={status.status === "running" ? "pulse-dot" : ""}
              style={{
                width: 8, height: 8, borderRadius: "50%",
                background: statusMeta.color,
                display: "inline-block",
                position: "relative",
              }}
            />
            <span style={{ color: "var(--ink-bright)", fontSize: 13, fontWeight: 500 }}>
              {statusMeta.label}
            </span>
          </div>
        </header>

        {/* Error banner — prominent at top */}
        {status.last_error && (
          <div className="glass rise rise-2" style={{
            padding: "14px 18px",
            marginBottom: 20,
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            borderColor: "rgba(255, 120, 120, 0.30)",
            background: "rgba(255, 80, 80, 0.06)",
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
                color: "rgba(255, 200, 200, 0.96)",
                fontSize: 13.5,
                fontWeight: 500,
                marginBottom: 2,
              }}>
                Last run failed
              </div>
              <div style={{
                color: "rgba(255, 200, 200, 0.78)",
                fontSize: 13,
                wordBreak: "break-word",
              }}>
                {status.last_error}
              </div>
            </div>
          </div>
        )}

        {/* Hero: Cadence */}
        <GlassCard className="rise rise-2" style={{
          padding: "32px 34px",
          marginBottom: 20,
        }}>
          <div style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) auto",
            gap: 32,
            alignItems: "center",
          }}>
            <div>
              <FieldLabel>Cadence</FieldLabel>
              <div style={{
                fontSize: "clamp(1.9rem, 4vw, 2.6rem)",
                fontWeight: 600,
                letterSpacing: "-0.025em",
                lineHeight: 1.0,
                color: "var(--ink-bright)",
                marginBottom: 6,
              }}>
                Every {settings.schedule_days} {settings.schedule_days === 1 ? "day" : "days"}
              </div>
              <div style={{ color: "var(--ink-soft)", fontSize: 13.5 }}>
                Last run · {formatDate(status.last_run)}
              </div>
            </div>

            <div style={{
              fontSize: 96,
              lineHeight: 0.9,
              fontWeight: 200,
              color: "var(--ink-bright)",
              letterSpacing: "-0.06em",
              textAlign: "right",
              minWidth: 90,
              fontVariantNumeric: "tabular-nums",
            }}>
              {settings.schedule_days}
            </div>
          </div>

          <div style={{ marginTop: 24 }}>
            <input
              type="range"
              min={1}
              max={30}
              value={settings.schedule_days}
              onChange={(e) =>
                setSettings((s) => ({ ...s, schedule_days: Number(e.target.value) }))
              }
              className="slider-glass"
              style={{ "--fill": `${fillPct}%` } as React.CSSProperties}
              aria-label="Schedule frequency in days"
            />
            <div style={{
              display: "flex", justifyContent: "space-between",
              color: "var(--ink-muted)", fontSize: 12, marginTop: 10,
            }}>
              <span>Daily</span>
              <span>Weekly</span>
              <span>Monthly</span>
            </div>
          </div>
        </GlassCard>

        {/* Two-col forms */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 20,
          marginBottom: 20,
        }}>
          {/* Accounts */}
          <GlassCard className="rise rise-3">
            <h2 style={{ fontSize: 16, fontWeight: 600, color: "var(--ink-bright)" }}>
              Accounts
            </h2>
            <p style={{ color: "var(--ink-soft)", fontSize: 13.5, marginTop: 4, marginBottom: 18 }}>
              Instagram handles to watch. No @ needed.
            </p>

            <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
              <input
                className="input-glass"
                placeholder="nike"
                value={accountInput}
                onChange={(e) => setAccountInput(e.target.value)}
                onKeyDown={handleKeyDown(addAccount)}
              />
              <button onClick={addAccount} className="btn btn-glass" aria-label="Add account">
                <IconPlus /> Add
              </button>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, minHeight: 36 }}>
              {settings.accounts.length === 0 ? (
                <span style={{ color: "var(--ink-muted)", fontSize: 13.5 }}>
                  No accounts yet
                </span>
              ) : (
                settings.accounts.map((a) => (
                  <Tag key={a} label={`@${a}`} onRemove={() => removeAccount(a)} />
                ))
              )}
            </div>
          </GlassCard>

          {/* Emails */}
          <GlassCard className="rise rise-4">
            <h2 style={{ fontSize: 16, fontWeight: 600, color: "var(--ink-bright)" }}>
              Recipients
            </h2>
            <p style={{ color: "var(--ink-soft)", fontSize: 13.5, marginTop: 4, marginBottom: 18 }}>
              Where the report email lands.
            </p>

            <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
              <input
                className="input-glass"
                placeholder="team@company.com"
                type="email"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                onKeyDown={handleKeyDown(addEmail)}
              />
              <button onClick={addEmail} className="btn btn-glass" aria-label="Add recipient">
                <IconPlus /> Add
              </button>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, minHeight: 36 }}>
              {settings.recipient_emails.length === 0 ? (
                <span style={{ color: "var(--ink-muted)", fontSize: 13.5 }}>
                  No recipients yet
                </span>
              ) : (
                settings.recipient_emails.map((e) => (
                  <Tag key={e} label={e} onRemove={() => removeEmail(e)} />
                ))
              )}
            </div>
          </GlassCard>
        </div>

        {/* Hint card explaining the buttons */}
        <div className="rise rise-5" style={{
          color: "var(--ink-muted)",
          fontSize: 12.5,
          textAlign: "center",
          marginBottom: 4,
        }}>
          <strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>Save</strong> stores your settings and updates the schedule.{" "}
          <strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>Run now</strong> generates a report and emails it immediately.
        </div>

        {/* Floating action dock */}
        <div className="glass rise rise-6" style={{
          position: "fixed",
          left: "50%",
          bottom: 24,
          transform: "translateX(-50%)",
          width: "calc(100% - 40px)",
          maxWidth: 880,
          padding: "14px 18px 14px 22px",
          borderRadius: "var(--radius-pill)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          zIndex: 50,
        }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            {saveMsg && (
              <span style={{
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
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={saveSettings} disabled={saving} className="btn btn-glass">
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
    </>
  );
}
