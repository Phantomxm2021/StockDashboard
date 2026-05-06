from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass
class MainlineStrategyConfig:
    min_amount: float = 100_000_000
    min_change_pct: float = 1.0
    max_change_pct: float = 9.8
    min_turnover: float = 3.0
    max_turnover: float = 35.0
    require_turnover: bool = False
    exclude_st: bool = True
    exclude_bj: bool = True
    amount_top_n: int = 200
    gain_top_n: int = 200
    a_pool_min_score: float = 65
    b_pool_min_score: float = 55


@dataclass(frozen=True)
class MarketContext:
    state: str = "normal"
    amount_yi: float = 0.0

    @property
    def label(self) -> str:
        if self.state == "shrinking":
            return "缩量"
        if self.state == "expanding":
            return "放量"
        return "平量"


def config_to_df(config: MainlineStrategyConfig) -> pd.DataFrame:
    return pd.DataFrame([{"参数": key, "值": value} for key, value in asdict(config).items()])


def normalize_code(code: object) -> str:
    if pd.isna(code):
        return ""
    code_str = str(code).strip()
    digits = "".join(ch for ch in code_str if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return digits.zfill(6) if digits else ""


def is_bj_stock(code: str) -> bool:
    code = normalize_code(code)
    return code.startswith("8") or code.startswith("4")


def build_mainline_candidates(
    *,
    config: MainlineStrategyConfig,
    quote_df: pd.DataFrame,
    amount_rank_df: pd.DataFrame,
    gain_rank_df: pd.DataFrame,
    lhb_df: pd.DataFrame,
    enrichment_df: pd.DataFrame | None = None,
    market_context: MarketContext | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    market = market_context or MarketContext()
    df_all = quote_df.copy()
    if df_all.empty:
        return df_all, df_all.copy()

    df_all["code"] = df_all["code"].apply(normalize_code)
    df_all["代码"] = df_all["code"]
    df_all["成交额亿"] = pd.to_numeric(df_all["成交额"], errors="coerce") / 100_000_000
    df_all["涨跌幅"] = pd.to_numeric(df_all["涨跌幅"], errors="coerce")
    if "换手率" in df_all.columns:
        df_all["换手率"] = pd.to_numeric(df_all["换手率"], errors="coerce")
    else:
        df_all["换手率"] = pd.NA
        df_all["有换手率数据"] = False

    df_all = _merge_enrichment(df_all, enrichment_df)
    df_all["市场环境"] = market.label
    df_all["排除原因"] = df_all.apply(lambda row: _exclude_reasons(row, config, market), axis=1)
    base_mask = _base_mask(df_all, config, market)
    candidates_df = df_all[base_mask].copy()
    excluded_df = df_all[~base_mask].copy()

    if candidates_df.empty:
        return candidates_df, _excluded_columns(excluded_df)

    amount_codes = _codes(amount_rank_df)
    gain_codes = _codes(gain_rank_df)
    lhb_codes = _codes(lhb_df)

    candidates_df["个股强度分"] = candidates_df.apply(
        lambda row: _individual_strength(row, amount_codes, gain_codes, market),
        axis=1,
    )
    candidates_df["板块强度分"] = candidates_df["板块强度分"].fillna(0).clip(lower=0, upper=25)
    candidates_df["资金流向分"] = (
        candidates_df["资金流向分"].fillna(0)
        + candidates_df["code"].isin(lhb_codes).astype(float) * 4
    ).clip(lower=0, upper=20)
    candidates_df["位置风险分"] = candidates_df.apply(_position_risk_score, axis=1)
    candidates_df["新闻催化分"] = candidates_df["新闻催化分"].fillna(0).clip(lower=0, upper=10)
    candidates_df["主线强势分"] = (
        candidates_df["个股强度分"]
        + candidates_df["板块强度分"]
        + candidates_df["资金流向分"]
        + candidates_df["位置风险分"]
        + candidates_df["新闻催化分"]
    ).round(2)
    candidates_df["买入观察等级"] = candidates_df.apply(
        lambda row: _watch_level(row, config),
        axis=1,
    )
    candidates_df["次日动作建议"] = candidates_df.apply(_action_suggestion, axis=1)
    candidates_df = candidates_df.sort_values(
        ["买入观察等级", "主线强势分"],
        ascending=[True, False],
    )

    keep_cols = [
        "code", "代码", "名称", "最新价", "涨跌幅", "成交额亿",
        "市场环境", "主线板块", "个股强度分", "板块强度分", "资金流向分",
        "位置风险分", "新闻催化分", "主线强势分",
        "买入观察等级", "次日动作建议", "数据源",
    ]
    candidates_df = candidates_df[[col for col in keep_cols if col in candidates_df.columns]].copy()
    return candidates_df, _excluded_columns(excluded_df)


def _merge_enrichment(df: pd.DataFrame, enrichment_df: pd.DataFrame | None) -> pd.DataFrame:
    default_columns: dict[str, Any] = {
        "主线板块": "",
        "板块强度分": 0.0,
        "资金流向分": 0.0,
        "新闻催化分": 0.0,
    }
    if enrichment_df is None or enrichment_df.empty or "code" not in enrichment_df.columns:
        out = df.copy()
        for col, value in default_columns.items():
            out[col] = value
        return out

    enrich = enrichment_df.copy()
    enrich["code"] = enrich["code"].apply(normalize_code)
    for col, value in default_columns.items():
        if col not in enrich.columns:
            enrich[col] = value
    out = df.merge(enrich[["code", *default_columns.keys()]], on="code", how="left")
    for col, value in default_columns.items():
        out[col] = out[col].fillna(value)
    return out


def _exclude_reasons(row: pd.Series, config: MainlineStrategyConfig, market: MarketContext) -> str:
    reasons: list[str] = []
    name = str(row.get("名称", ""))
    code = normalize_code(row.get("code", ""))
    change_pct = row.get("涨跌幅")
    amount = row.get("成交额")
    turnover = row.get("换手率")
    has_turnover = bool(row.get("有换手率数据", False))

    if config.exclude_st and ("ST" in name or "退" in name):
        reasons.append("ST/退市风险")
    if config.exclude_bj and is_bj_stock(code):
        reasons.append("北交所默认排除")
    if market.state == "shrinking" and _is_star_market(code):
        reasons.append("缩量不做科创板")
    if pd.notna(amount) and amount < config.min_amount:
        reasons.append(f"成交额不足<{config.min_amount / 100000000:.1f}亿")
    if pd.notna(change_pct) and change_pct < config.min_change_pct:
        reasons.append(f"涨幅偏弱<{config.min_change_pct}%")
    if pd.notna(change_pct) and change_pct > config.max_change_pct:
        reasons.append(f"涨幅过高>{config.max_change_pct}%")
    if has_turnover or config.require_turnover:
        if pd.isna(turnover):
            reasons.append("缺少换手率数据")
        elif turnover < config.min_turnover:
            reasons.append(f"换手率不足<{config.min_turnover}%")
        elif turnover > config.max_turnover:
            reasons.append(f"换手率过高>{config.max_turnover}%")
    return "；".join(reasons)


def _base_mask(df: pd.DataFrame, config: MainlineStrategyConfig, market: MarketContext) -> pd.Series:
    mask = (
        (df["成交额"] >= config.min_amount)
        & (df["涨跌幅"] >= config.min_change_pct)
        & (df["涨跌幅"] <= config.max_change_pct)
    )
    if config.exclude_st:
        mask = mask & (~df["名称"].astype(str).str.contains("ST|退", regex=True, na=False))
    if config.exclude_bj:
        mask = mask & (~df["code"].apply(is_bj_stock))
    if market.state == "shrinking":
        mask = mask & (~df["code"].apply(_is_star_market))

    has_real_turnover = "有换手率数据" in df.columns and df["有换手率数据"].fillna(False).any()
    if config.require_turnover or has_real_turnover:
        mask = mask & (df["换手率"] >= config.min_turnover) & (df["换手率"] <= config.max_turnover)
    return mask


def _codes(df: pd.DataFrame) -> set[str]:
    if df is None or df.empty or "code" not in df.columns:
        return set()
    return set(df["code"].apply(normalize_code))


def _individual_strength(row: pd.Series, amount_codes: set[str], gain_codes: set[str], market: MarketContext) -> float:
    score = 0.0
    code = normalize_code(row.get("code", ""))
    change_pct = float(row.get("涨跌幅", 0) or 0)
    amount_yi = float(row.get("成交额亿", 0) or 0)
    if code in amount_codes:
        score += 10
    if code in gain_codes:
        score += 8
    if 2 <= change_pct <= 7:
        score += min((change_pct - 2) / 5 * 4, 4)
    score += min(amount_yi / 20 * 3, 3)
    code = normalize_code(row.get("code", ""))
    if market.state == "expanding":
        if _is_chinext(code):
            score += 4
        elif _is_star_market(code):
            score += 3
    return round(min(score, 25), 2)


def _position_risk_score(row: pd.Series) -> float:
    score = 20.0
    change_pct = float(row.get("涨跌幅", 0) or 0)
    turnover = row.get("换手率")
    recent_gain = float(row.get("近5日涨幅", 0) or 0)
    if change_pct >= 9.3:
        score -= 12
    elif change_pct >= 8:
        score -= 8
    if pd.notna(turnover) and float(turnover) >= 25:
        score -= 7
    if recent_gain >= 25:
        score -= 8
    elif recent_gain >= 18:
        score -= 5
    return round(max(score, 0), 2)


def _watch_level(row: pd.Series, config: MainlineStrategyConfig) -> str:
    score = float(row.get("主线强势分", 0) or 0)
    position_risk_score = float(row.get("位置风险分", 0) or 0)
    individual_score = float(row.get("个股强度分", 0) or 0)
    sector_score = float(row.get("板块强度分", 0) or 0)
    fund_score = float(row.get("资金流向分", 0) or 0)
    catalyst_score = float(row.get("新闻催化分", 0) or 0)
    if position_risk_score < 10:
        return "C_暂缓跟踪"
    has_mainline_confirmation = sector_score >= 12 and fund_score >= 6
    has_catalyst_confirmation = sector_score >= 16 and catalyst_score >= 6
    has_strong_fund_confirmation = fund_score >= 8 and individual_score >= 18
    enrichment_missing = sector_score == 0 and fund_score == 0
    if str(row.get("市场环境", "")) == "放量" and _is_star_market(row.get("code", "")) and fund_score < 6:
        return "B_继续观察" if score >= config.b_pool_min_score else "C_暂缓跟踪"
    if has_strong_fund_confirmation:
        return "A_核心关注"
    required_score = config.a_pool_min_score
    if str(row.get("市场环境", "")) == "放量" and _is_chinext(row.get("code", "")):
        required_score -= 5
    if score >= required_score and (has_mainline_confirmation or has_catalyst_confirmation):
        return "A_核心关注"
    if enrichment_missing and individual_score >= 18 and score >= 40:
        return "B_继续观察"
    if score >= config.b_pool_min_score:
        return "B_继续观察"
    return "C_暂缓跟踪"


def _action_suggestion(row: pd.Series) -> str:
    level = str(row.get("买入观察等级", ""))
    sector = str(row.get("主线板块", "")).strip()
    if level.startswith("A_"):
        return f"主线强势确认：重点看{sector or '所属板块'}延续、资金承接和开盘不过热。"
    if level.startswith("B_"):
        return "继续观察：需要板块强度或资金流进一步确认后再升级。"
    return "暂缓跟踪：位置风险、板块强度或资金流条件不足。"


def _excluded_columns(excluded_df: pd.DataFrame) -> pd.DataFrame:
    if excluded_df.empty:
        return excluded_df.copy()
    keep_cols = [
        "code", "代码", "名称", "最新价", "涨跌幅", "成交额亿",
        "市场环境", "主线板块", "排除原因", "数据源",
    ]
    return excluded_df[[col for col in keep_cols if col in excluded_df.columns]].copy()


def _is_chinext(code: object) -> bool:
    code = normalize_code(code)
    return code.startswith("300") or code.startswith("301")


def _is_star_market(code: object) -> bool:
    code = normalize_code(code)
    return code.startswith("688") or code.startswith("689")
