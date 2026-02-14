from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd

VALID_STATUS = {"交易成功", "已发货"}

FIELD_ALIASES = {
    "order_no": [
        "订单号",
        "订单编号",
        "子订单号",
        "单号",
        "订单",
        "order",
        "orderid",
        "orderno",
        "订单id",
    ],
    "product_name": ["商品名称", "产品", "商品", "货品", "宝贝名称", "item", "product"],
    "status": ["订单状态", "状态", "交易状态", "发货状态", "status"],
    "sales_amount": ["实付金额", "销售金额", "付款金额", "订单金额", "成交金额", "销售额", "amount", "paid"],
    "cost_amount": ["成本价", "进货价", "成本", "采购价", "成本金额", "cost"],
}


@dataclass
class ReconcileResult:
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    duplicates: dict[str, int]
    mappings: dict[str, dict[str, str]]


def normalize_col_name(col: Any) -> str:
    text = str(col or "").strip().lower()
    text = re.sub(r"[\s_\-()（）\[\]【】]+", "", text)
    return text


def guess_column(columns: Iterable[Any], aliases: list[str]) -> Optional[str]:
    normalized = {normalize_col_name(c): c for c in columns}
    alias_norm = [normalize_col_name(a) for a in aliases]

    for a in alias_norm:
        if a in normalized:
            return normalized[a]

    for norm_col, original in normalized.items():
        if any(a in norm_col or norm_col in a for a in alias_norm):
            return original

    return None


def build_mapping(df: pd.DataFrame, manual: Optional[Dict[str, str]] = None) -> dict[str, str]:
    manual = manual or {}
    mapping: dict[str, str] = {}
    for key, aliases in FIELD_ALIASES.items():
        if manual.get(key) and manual[key] in df.columns:
            mapping[key] = manual[key]
            continue
        guessed = guess_column(df.columns, aliases)
        if guessed:
            mapping[key] = guessed
    return mapping


def clean_order_no(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[\s\-_,.;:：#]+", "", text)
    digits = re.sub(r"\D", "", text)
    return digits if digits else None


def parse_money(value: Any) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace("¥", "").replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else 0.0


def normalize_status(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip()


def prepare_df(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    prepared = pd.DataFrame()
    prepared["订单号"] = df.get(mapping.get("order_no", ""), pd.Series(dtype="object")).map(clean_order_no)
    prepared["商品名称"] = df.get(mapping.get("product_name", ""), pd.Series(dtype="object")).fillna("").astype(str)
    prepared["订单状态"] = df.get(mapping.get("status", ""), pd.Series(dtype="object")).map(normalize_status)
    prepared["销售金额"] = df.get(mapping.get("sales_amount", ""), pd.Series(dtype="object")).map(parse_money)
    prepared["成本"] = df.get(mapping.get("cost_amount", ""), pd.Series(dtype="object")).map(parse_money)

    prepared = prepared[prepared["订单状态"].isin(VALID_STATUS)]
    prepared = prepared[prepared["订单号"].notna()]
    prepared = prepared[prepared["订单号"].str.fullmatch(r"\d+")]

    grouped = (
        prepared.groupby("订单号", as_index=False)
        .agg({
            "商品名称": lambda x: " | ".join(sorted({v for v in x if v})),
            "订单状态": "first",
            "销售金额": "sum",
            "成本": "sum",
        })
    )
    return grouped


def find_duplicates(df: pd.DataFrame, order_col: str) -> dict[str, int]:
    if order_col not in df.columns:
        return {}
    cleaned = df[order_col].map(clean_order_no)
    counts = cleaned.value_counts(dropna=True)
    return {k: int(v) for k, v in counts.items() if v > 1 and k is not None}


def reconcile(
    official_df: pd.DataFrame,
    customer_df: pd.DataFrame,
    official_manual: Optional[Dict[str, str]] = None,
    customer_manual: Optional[Dict[str, str]] = None,
) -> ReconcileResult:
    official_map = build_mapping(official_df, official_manual)
    customer_map = build_mapping(customer_df, customer_manual)

    required = {"order_no", "status", "sales_amount", "cost_amount"}
    missing_official = required - set(official_map)
    missing_customer = required - set(customer_map)
    if missing_official or missing_customer:
        missing_msgs = []
        if missing_official:
            missing_msgs.append(f"官方表缺少字段映射: {', '.join(sorted(missing_official))}")
        if missing_customer:
            missing_msgs.append(f"客服表缺少字段映射: {', '.join(sorted(missing_customer))}")
        raise ValueError("；".join(missing_msgs))

    official_dup = find_duplicates(official_df, official_map["order_no"])
    customer_dup = find_duplicates(customer_df, customer_map["order_no"])

    off = prepare_df(official_df, official_map)
    cus = prepare_df(customer_df, customer_map)

    merged = off.merge(cus, on="订单号", how="outer", suffixes=("_官方", "_客服"), indicator=True)

    rows: list[dict[str, Any]] = []
    seq = 1
    total_sales = 0.0
    total_cost = 0.0

    for _, row in merged.iterrows():
        source = row["_merge"]
        if source == "both":
            sales = float(row["销售金额_官方"])
            cost = float(row["成本_官方"])
            product = row.get("商品名称_官方") or row.get("商品名称_客服") or ""
            status = "正常匹配"
        elif source == "left_only":
            sales = float(row["销售金额_官方"])
            cost = float(row["成本_官方"])
            product = row.get("商品名称_官方", "")
            status = "客服漏记"
        else:
            sales = float(row["销售金额_客服"])
            cost = float(row["成本_客服"])
            product = row.get("商品名称_客服", "")
            status = "客服多记"

        profit = sales - cost
        if profit < 0:
            status = f"{status} / 亏损订单"

        total_sales += sales
        total_cost += cost

        rows.append(
            {
                "序号": seq,
                "订单号": row["订单号"],
                "商品名称": product,
                "销售金额": round(sales, 2),
                "成本": round(cost, 2),
                "单笔利润": round(profit, 2),
                "状态标记": status,
            }
        )
        seq += 1

    summary = {
        "总销售额": round(total_sales, 2),
        "总成本": round(total_cost, 2),
        "总利润": round(total_sales - total_cost, 2),
        "订单总数": len(rows),
    }

    return ReconcileResult(
        rows=rows,
        summary=summary,
        duplicates={"官方": len(official_dup), "客服": len(customer_dup)},
        mappings={"官方": official_map, "客服": customer_map},
    )
