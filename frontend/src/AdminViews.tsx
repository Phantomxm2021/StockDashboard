import { FormEvent, useEffect, useRef, useState } from "react";
import {
  createUser,
  fetchJob,
  fetchStatus,
  fetchUsers,
  runJob,
  type JobPayload,
  type ReportDefinition,
  type StatusPayload,
  type User
} from "./api";

type AdminViewsProps = {
  token: string;
  market: string;
  reports: ReportDefinition[];
  view: "status" | "jobs" | "users";
};

export function AdminViews({ token, market, reports, view }: AdminViewsProps) {
  if (view === "status") return <StatusPanel token={token} market={market} />;
  if (view === "jobs") return <JobsPanel token={token} market={market} reports={reports} />;
  return <UsersPanel token={token} />;
}

function StatusPanel({ token, market }: { token: string; market: string }) {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setStatus(null);
    fetchStatus(token, market)
      .then((payload) => {
        if (!cancelled) setStatus(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [token, market]);

  return (
    <section className="table-panel">
      <div className="table-toolbar">
        <strong>运行状态</strong>
      </div>
      {error ? <div className="empty-state">{error}</div> : null}
      <pre className="status-block">{JSON.stringify(status ?? {}, null, 2)}</pre>
    </section>
  );
}

function JobsPanel({ token, market, reports }: { token: string; market: string; reports: ReportDefinition[] }) {
  const [result, setResult] = useState<JobPayload | null>(null);
  const [error, setError] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const currentMarketRef = useRef(market);

  useEffect(() => {
    currentMarketRef.current = market;
    setResult(null);
    setError("");
    setIsRunning(false);
  }, [market]);

  async function handleRun(reportType: string) {
    setIsRunning(true);
    setError("");
    setResult(null);
    try {
      const payload = await runJob(token, market, reportType);
      if (payload.market === currentMarketRef.current) {
        setResult(payload);
      }
    } catch (err) {
      if (market === currentMarketRef.current) {
        setError(err instanceof Error ? err.message : "任务失败");
      }
    } finally {
      if (market === currentMarketRef.current) {
        setIsRunning(false);
      }
    }
  }

  useEffect(() => {
    if (!result || result.status === "succeeded" || result.status === "failed") {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      fetchJob(token, result.job_id)
        .then((payload) => {
          if (!cancelled && payload.market === currentMarketRef.current) setResult(payload);
        })
        .catch((err) => {
          if (!cancelled && market === currentMarketRef.current) {
            setError(err instanceof Error ? err.message : "任务状态获取失败");
          }
        });
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [token, market, result]);

  return (
    <section className="table-panel">
      <div className="table-toolbar">
        <strong>任务中心</strong>
      </div>
      <div className="button-row">
        {reports.map((report, index) => (
          <button
            key={report.id}
            className={index === 0 ? "primary-button compact" : "secondary-button"}
            disabled={isRunning}
            onClick={() => handleRun(report.id)}
          >
            运行{report.title}
          </button>
        ))}
      </div>
      {error ? <div className="empty-state">{error}</div> : null}
      {result ? (
        <>
          <div className="job-progress">
            <span className={`job-dot ${result.status}`} />
            <strong>{jobStatusText(result.status)}</strong>
            <span>{reports.find((report) => report.id === result.report_type)?.title ?? result.report_type}</span>
          </div>
          {(result.status === "queued" || result.status === "running") ? <TaskSkeleton /> : null}
          <pre className="status-block">{result.logs || `returncode=${result.returncode}`}</pre>
        </>
      ) : null}
    </section>
  );
}

function jobStatusText(status: JobPayload["status"]): string {
  const labels: Record<JobPayload["status"], string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败"
  };
  return labels[status];
}

function TaskSkeleton() {
  return (
    <div className="task-skeleton">
      <span />
      <span />
      <span />
    </div>
  );
}

function UsersPanel({ token }: { token: string }) {
  const [users, setUsers] = useState<User[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function loadUsers() {
    fetchUsers(token)
      .then(setUsers)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }

  useEffect(loadUsers, [token]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      await createUser(token, username, password);
      setUsername("");
      setPassword("");
      loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  return (
    <section className="content-grid">
      <form className="admin-card" onSubmit={handleSubmit}>
        <h2>新增用户</h2>
        <label>
          <span>用户名</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          <span>密码</span>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error ? <div className="form-error">{error}</div> : null}
        <button className="primary-button" type="submit">
          创建用户
        </button>
      </form>
      <section className="admin-card">
        <h2>用户列表</h2>
        <div className="user-list">
          {users.map((user) => (
            <div key={user.username}>
              <strong>{user.username}</strong>
              <span>{user.is_root ? "管理员" : "用户"}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
