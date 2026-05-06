import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, HelpCircle, RefreshCw } from "lucide-react";
import { fetchReport, type ReportPayload } from "./api";

type ReportViewProps = {
  token: string;
  market: string;
  reportType: string;
  title: string;
};

const PAGE_SIZE = 50;

export function ReportView({ token, market, reportType, title }: ReportViewProps) {
  const [pool, setPool] = useState("core");
  const [page, setPage] = useState(1);
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    setPool("core");
    setPage(1);
    setReport(null);
    setTooltip(null);
    setError("");
  }, [market, reportType]);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError("");
    fetchReport(token, market, reportType, pool, page, PAGE_SIZE)
      .then((payload) => {
        if (!cancelled) setReport(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, market, reportType, pool, page]);

  return (
    <section className="content-stack">
      <div className="section-header">
        <div>
          <span className="eyebrow">{title}</span>
          <h2>观察池</h2>
        </div>
        <button className="secondary-button" onClick={() => setPage(1)}>
          <RefreshCw size={16} />
          刷新
        </button>
      </div>

      {report ? (
        <div className="metric-grid">
          {report.pools.map((item) => (
            <button
              key={item.key}
              className={`metric-card ${pool === item.key ? "selected" : ""}`}
              onClick={() => {
                setPool(item.key);
                setPage(1);
              }}
            >
              <span>{item.title}</span>
              <strong>{item.count}</strong>
            </button>
          ))}
        </div>
      ) : null}

      <div className="table-panel">
        <div className="table-toolbar">
          <strong>{report?.pools.find((item) => item.key === report.active_pool)?.title ?? "核心关注"}</strong>
          {report ? (
            <span>
              {report.pagination.total} 条，页 {report.pagination.page} / {report.pagination.total_pages}
            </span>
          ) : null}
        </div>

        {error ? <div className="empty-state">{error}</div> : null}
        {isLoading ? <SkeletonTable /> : null}
        {!isLoading && report && report.rows.length === 0 ? <div className="empty-state">暂无数据</div> : null}

        {!isLoading && report && report.rows.length > 0 ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {report.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row, index) => (
                  <tr key={`${row.code ?? row["代码"] ?? index}`}>
                    {report.columns.map((column) => (
                      <td key={column}>{renderCell(column, row[column], setTooltip)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {report ? (
          <div className="pagination">
            <button className="secondary-button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
              <ChevronLeft size={16} />
              上一页
            </button>
            <button
              className="secondary-button"
              disabled={page >= report.pagination.total_pages}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
              <ChevronRight size={16} />
            </button>
          </div>
        ) : null}
      </div>
      {tooltip ? (
        <div className="tooltip-layer" style={{ left: tooltip.x, top: tooltip.y }}>
          {tooltip.text}
        </div>
      ) : null}
    </section>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function renderCell(
  column: string,
  value: unknown,
  setTooltip: (tooltip: { text: string; x: number; y: number } | null) => void
) {
  if (column === "次日动作建议") {
    const text = formatCell(value);
    if (!text) return "";
    return (
      <span
        className="help-tooltip"
        tabIndex={0}
        aria-label={`次日动作建议：${text}`}
        onMouseEnter={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setTooltip({ text, x: Math.min(rect.left, window.innerWidth - 300), y: rect.bottom + 10 });
        }}
        onMouseLeave={() => setTooltip(null)}
        onFocus={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setTooltip({ text, x: Math.min(rect.left, window.innerWidth - 300), y: rect.bottom + 10 });
        }}
        onBlur={() => setTooltip(null)}
      >
        <HelpCircle size={16} />
      </span>
    );
  }
  return formatCell(value);
}

function SkeletonTable() {
  return (
    <div className="skeleton-wrap" aria-label="加载中">
      {Array.from({ length: 8 }).map((_, rowIndex) => (
        <div className="skeleton-row" key={rowIndex}>
          {Array.from({ length: 6 }).map((__, cellIndex) => (
            <span className="skeleton-cell" key={cellIndex} />
          ))}
        </div>
      ))}
    </div>
  );
}
