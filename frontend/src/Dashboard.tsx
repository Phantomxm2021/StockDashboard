import { Activity, LogOut, PlayCircle, Settings, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchMarkets, type MarketDefinition, type User } from "./api";
import { AdminViews } from "./AdminViews";
import { ReportView } from "./ReportView";

type DashboardProps = {
  token: string;
  user: User;
  onLogout: () => void;
};

type AdminView = "status" | "jobs" | "users";
type View = string | AdminView;

export function Dashboard({ token, user, onLogout }: DashboardProps) {
  const [markets, setMarkets] = useState<MarketDefinition[]>([]);
  const [activeMarketId, setActiveMarketId] = useState("");
  const [view, setView] = useState<View>("");
  const [marketError, setMarketError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setMarketError("");
    fetchMarkets(token)
      .then((payload) => {
        if (cancelled) return;
        setMarkets(payload);
        const firstMarket = payload[0];
        if (firstMarket) {
          setActiveMarketId((current) => current || firstMarket.id);
          setView((current) => current || firstMarket.default_report_type);
        }
      })
      .catch((err) => {
        if (!cancelled) setMarketError(err instanceof Error ? err.message : "市场加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const activeMarket = useMemo(
    () => markets.find((market) => market.id === activeMarketId) ?? markets[0] ?? null,
    [activeMarketId, markets]
  );
  const selectedReport = activeMarket?.reports.find((report) => report.id === view);
  const allowedView = user.is_root || selectedReport ? view : activeMarket?.default_report_type ?? "";
  const activeTitle = isAdminView(allowedView)
    ? titleForAdminView(allowedView)
    : activeMarket?.reports.find((report) => report.id === allowedView)?.title ?? "";

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Activity size={24} />
          <div>
            <strong>多市场观察池</strong>
            <span>Stock Dashboard</span>
          </div>
        </div>
        <div className="market-picker">
          <label className="sidebar-label" htmlFor="market-select">
            市场
          </label>
          <select
            id="market-select"
            className="market-select"
            value={activeMarket?.id ?? ""}
            onChange={(event) => {
              const next = markets.find((item) => item.id === event.target.value);
              if (next) {
                setActiveMarketId(next.id);
                setView(next.default_report_type);
              }
            }}
          >
            {markets.map((market) => (
              <option key={market.id} value={market.id}>
                {market.name}
              </option>
            ))}
          </select>
        </div>
        <nav className="nav-list">
          {activeMarket?.reports.map((report) => (
            <button key={report.id} className={allowedView === report.id ? "active" : ""} onClick={() => setView(report.id)}>
              {report.title}
            </button>
          ))}
          {user.is_root ? (
            <>
              <button className={allowedView === "status" ? "active" : ""} onClick={() => setView("status")}>
                <Settings size={16} />
                运行状态
              </button>
              <button className={allowedView === "jobs" ? "active" : ""} onClick={() => setView("jobs")}>
                <PlayCircle size={16} />
                任务中心
              </button>
              <button className={allowedView === "users" ? "active" : ""} onClick={() => setView("users")}>
                <Users size={16} />
                用户管理
              </button>
            </>
          ) : null}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">{activeMarket?.name ?? (user.is_root ? "管理员" : "用户")}</span>
            <h1>{activeTitle || "观察池"}</h1>
          </div>
          <div className="user-actions">
            <span>{user.username}</span>
            <button className="icon-button" onClick={onLogout} aria-label="退出登录">
              <LogOut size={18} />
            </button>
          </div>
        </header>

        {marketError ? <div className="empty-state">{marketError}</div> : null}
        {activeMarket && !isAdminView(allowedView) ? (
          <ReportView token={token} market={activeMarket.id} reportType={allowedView} title={activeTitle} />
        ) : null}
        {user.is_root && activeMarket && allowedView === "status" ? (
          <AdminViews token={token} market={activeMarket.id} reports={activeMarket.reports} view="status" />
        ) : null}
        {user.is_root && activeMarket && allowedView === "jobs" ? (
          <AdminViews token={token} market={activeMarket.id} reports={activeMarket.reports} view="jobs" />
        ) : null}
        {user.is_root && activeMarket && allowedView === "users" ? (
          <AdminViews token={token} market={activeMarket.id} reports={activeMarket.reports} view="users" />
        ) : null}
      </section>
    </main>
  );
}

function isAdminView(view: View): view is AdminView {
  return view === "status" || view === "jobs" || view === "users";
}

function titleForAdminView(view: AdminView): string {
  const titles: Record<AdminView, string> = {
    status: "运行状态",
    jobs: "任务中心",
    users: "用户管理"
  };
  return titles[view];
}
