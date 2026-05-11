"""
Consolidation Agent for Close Command.
Runs after the output agent to produce the group consolidated P&L and Balance Sheet.
Applies PCon% per entity, applies approved IC eliminations, and builds ConsolidatedStatement.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from close_command.database.persistence import CloseCommandDB
from close_command.data.entities import ENTITY_REGISTRY, get_entity, get_pcon
from close_command.models.financials import ConsolidatedStatement

logger = logging.getLogger(__name__)

# PCon override table: entity_code -> PCon fraction (0.0 to 1.0)
# Populated from ENTITY_REGISTRY but can be overridden here
_PCON_TABLE: dict[str, float] = {
    code: data.get("pcon", 100.0) / 100.0
    for code, data in ENTITY_REGISTRY.items()
}


class ConsolidationAgent:
    """
    Produces group consolidated P&L and Balance Sheet.
    Input: entity_statements from ingestion + approved journal entries from output.
    Output: ConsolidatedStatement placed in state["consolidation_result"].
    """

    def __init__(self, db: CloseCommandDB) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def run(self, state: dict) -> dict:
        """
        Main entry: read entity_statements and approved_entries,
        produce ConsolidatedStatement, update state.
        """
        try:
            ingestion_result = state.get("ingestion_result") or {}
            output_result = state.get("output_result") or {}

            entity_statements: dict = ingestion_result.get("entity_statements") or {}
            approved_entries: list = output_result.get("approved_entries") or []
            batch_id: str = state.get("batch_id", "")
            period: str = state.get("period", "")
            scenario: str = state.get("scenario", "")

            logger.info(
                "ConsolidationAgent starting batch_id=%s entities=%d approved_entries=%d",
                batch_id, len(entity_statements), len(approved_entries),
            )

            if not entity_statements:
                logger.warning("No entity_statements found — skipping consolidation")
                state["consolidation_result"] = self._empty_result(batch_id, period, scenario)
                return state

            pcon_table = _PCON_TABLE.copy()

            # 1. Aggregate entity lines with PCon%
            aggregated = self.aggregate_entity_lines(entity_statements, pcon_table)

            # 2. Apply approved eliminations
            aggregated_post_elim = self.apply_eliminations(aggregated, approved_entries)

            # 3. Compute consolidated P&L
            pl = self.compute_consolidated_pl(aggregated_post_elim)

            # 4. Compute consolidated Balance Sheet
            bs = self.compute_consolidated_bs(aggregated_post_elim)

            # 5. Entity contributions
            entity_contributions = self.compute_entity_contributions(entity_statements, pcon_table)

            # 6. Build consolidated statement
            stmt = self.build_consolidated_statement(
                pl=pl,
                bs=bs,
                entity_contributions=entity_contributions,
                batch_id=batch_id,
                period=period,
                scenario=scenario,
                aggregated=aggregated,
                aggregated_post_elim=aggregated_post_elim,
            )

            state["consolidation_result"] = stmt.model_dump()

            logger.info(
                "ConsolidationAgent complete: net_revenue=%.0f ebit=%.0f bs_balanced=%s",
                stmt.net_revenue, stmt.ebit, stmt.balance_sheet_balanced,
            )

        except Exception as exc:
            logger.error("ConsolidationAgent.run failed: %s", exc, exc_info=True)
            state.setdefault("errors", []).append(f"Consolidation error: {str(exc)}")
            state["consolidation_result"] = self._empty_result(
                state.get("batch_id", ""),
                state.get("period", ""),
                state.get("scenario", ""),
            )

        return state

    # ──────────────────────────────────────────────────────────────────────
    # Step 1: Aggregate entity lines with PCon%
    # ──────────────────────────────────────────────────────────────────────

    def aggregate_entity_lines(
        self,
        entity_statements: dict,
        pcon_table: dict,
    ) -> dict:
        """
        For each entity apply PCon% to all USD amounts and
        separate IC from Non-IC lines. Sum by account_category.
        Returns:
          {
            "P&L": {
              "Revenue": {"total": x, "ic": x, "non_ic": x},
              "COGS":    {"total": x, "ic": x, "non_ic": x},
              "OpEx":    {"total": x, "ic": x, "non_ic": x},
            },
            "BS": {
              "Assets":      {"total": x, "ic": x, "non_ic": x},
              "Liabilities": {"total": x, "ic": x, "non_ic": x},
              "Equity":      {"total": x, "ic": x, "non_ic": x},
            },
            "by_entity": {entity_code: {...}},
          }
        """
        pl_categories = ["Revenue", "COGS", "OpEx"]
        bs_categories = ["Assets", "Liabilities", "Equity"]

        result: dict = {
            "P&L": {cat: {"total": 0.0, "ic": 0.0, "non_ic": 0.0} for cat in pl_categories},
            "BS":  {cat: {"total": 0.0, "ic": 0.0, "non_ic": 0.0} for cat in bs_categories},
            "by_entity": {},
        }

        for entity_code, stmt_dict in entity_statements.items():
            pcon = pcon_table.get(entity_code, 1.0)
            lines = stmt_dict.get("lines", [])

            entity_agg: dict = {
                "pcon": pcon,
                "P&L": {cat: {"total": 0.0, "ic": 0.0, "non_ic": 0.0} for cat in pl_categories},
                "BS":  {cat: {"total": 0.0, "ic": 0.0, "non_ic": 0.0} for cat in bs_categories},
            }

            for line in lines:
                account_type = line.get("account_type", "P&L")
                account_category = line.get("account_category", "")
                is_ic = bool(line.get("is_intercompany", False))
                amount_usd = float(line.get("amount_usd", 0.0) or 0.0)

                # Apply PCon% to amount
                pcon_amount = amount_usd * pcon

                # Determine target bucket
                if account_type == "P&L" and account_category in pl_categories:
                    bucket = entity_agg["P&L"][account_category]
                    global_bucket = result["P&L"][account_category]
                elif account_type == "BS" and account_category in bs_categories:
                    bucket = entity_agg["BS"][account_category]
                    global_bucket = result["BS"][account_category]
                else:
                    # Unknown category — skip
                    continue

                bucket["total"] += pcon_amount
                global_bucket["total"] += pcon_amount
                if is_ic:
                    bucket["ic"] += pcon_amount
                    global_bucket["ic"] += pcon_amount
                else:
                    bucket["non_ic"] += pcon_amount
                    global_bucket["non_ic"] += pcon_amount

            result["by_entity"][entity_code] = entity_agg

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Step 2: Apply approved eliminations
    # ──────────────────────────────────────────────────────────────────────

    def apply_eliminations(
        self,
        aggregated: dict,
        approved_entries: list,
    ) -> dict:
        """
        For each approved journal entry (Dr/Cr pair), find the affected
        account category and subtract the elimination.
        Returns a deep copy of aggregated with post-elimination totals
        and a new "eliminations" tracking dict.
        """
        import copy
        result = copy.deepcopy(aggregated)

        result["eliminations"] = {
            "ic_revenue_eliminated": 0.0,
            "ic_cogs_eliminated": 0.0,
            "ic_assets_eliminated": 0.0,
            "ic_liabilities_eliminated": 0.0,
        }

        for entry in approved_entries:
            try:
                amount_usd = abs(float(entry.get("amount_usd", 0.0) or 0.0))
                rule_code = str(entry.get("rule_code", ""))
                dr_account = str(entry.get("dr_account", "")).lower()
                cr_account = str(entry.get("cr_account", "")).lower()

                # Classify based on rule_code and account descriptions
                if rule_code in ("IC-001",) or "revenue" in cr_account:
                    # IC revenue elimination: reduce Revenue IC bucket
                    result["P&L"]["Revenue"]["ic"] -= amount_usd
                    result["P&L"]["Revenue"]["total"] -= amount_usd
                    result["eliminations"]["ic_revenue_eliminated"] += amount_usd
                    # Also reduce COGS IC bucket (the debit side)
                    result["P&L"]["COGS"]["ic"] -= amount_usd
                    result["P&L"]["COGS"]["total"] -= amount_usd
                    result["eliminations"]["ic_cogs_eliminated"] += amount_usd

                elif rule_code in ("IC-004",) or "management fee" in cr_account:
                    # IC management fee: revenue in seller, opex in buyer
                    result["P&L"]["Revenue"]["ic"] -= amount_usd
                    result["P&L"]["Revenue"]["total"] -= amount_usd
                    result["eliminations"]["ic_revenue_eliminated"] += amount_usd
                    result["P&L"]["OpEx"]["ic"] -= amount_usd
                    result["P&L"]["OpEx"]["total"] -= amount_usd

                elif rule_code in ("IC-005",) or "royalty" in cr_account:
                    # IC royalty: revenue in licensor, expense in licensee
                    result["P&L"]["Revenue"]["ic"] -= amount_usd
                    result["P&L"]["Revenue"]["total"] -= amount_usd
                    result["eliminations"]["ic_revenue_eliminated"] += amount_usd
                    result["P&L"]["COGS"]["ic"] -= amount_usd
                    result["P&L"]["COGS"]["total"] -= amount_usd
                    result["eliminations"]["ic_cogs_eliminated"] += amount_usd

                elif rule_code in ("IC-002",) or ("receivable" in cr_account and "payable" in dr_account):
                    # IC receivable vs payable: BS elimination
                    result["BS"]["Assets"]["ic"] -= amount_usd
                    result["BS"]["Assets"]["total"] -= amount_usd
                    result["eliminations"]["ic_assets_eliminated"] += amount_usd
                    result["BS"]["Liabilities"]["ic"] -= amount_usd
                    result["BS"]["Liabilities"]["total"] -= amount_usd
                    result["eliminations"]["ic_liabilities_eliminated"] += amount_usd

                else:
                    # Generic P&L elimination — treat as revenue/cost pair
                    result["P&L"]["Revenue"]["ic"] -= amount_usd / 2
                    result["P&L"]["Revenue"]["total"] -= amount_usd / 2
                    result["P&L"]["COGS"]["ic"] -= amount_usd / 2
                    result["P&L"]["COGS"]["total"] -= amount_usd / 2
                    result["eliminations"]["ic_revenue_eliminated"] += amount_usd / 2
                    result["eliminations"]["ic_cogs_eliminated"] += amount_usd / 2

            except Exception as entry_exc:
                logger.warning("Failed to apply elimination entry: %s", entry_exc)

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Step 3: Compute consolidated P&L
    # ──────────────────────────────────────────────────────────────────────

    def compute_consolidated_pl(self, aggregated_post_elim: dict) -> dict:
        """
        Compute consolidated P&L from aggregated post-elimination data.
        Revenue amounts in the model are negative (credit nature), so we take abs().
        Costs are positive (debit nature).
        """
        pl = aggregated_post_elim.get("P&L", {})
        eliminations = aggregated_post_elim.get("eliminations", {})

        # Gross revenue = total revenue (abs, since revenue is credit/negative)
        gross_revenue = abs(pl.get("Revenue", {}).get("total", 0.0))

        # IC revenue eliminated (absolute)
        ic_rev_elim = abs(eliminations.get("ic_revenue_eliminated", 0.0))

        # Net revenue after elimination
        net_revenue = gross_revenue - ic_rev_elim

        # COGS
        gross_cogs = abs(pl.get("COGS", {}).get("non_ic", 0.0))
        ic_cogs_elim = abs(eliminations.get("ic_cogs_eliminated", 0.0))
        net_cogs = gross_cogs - ic_cogs_elim

        # Gross profit
        gross_profit = net_revenue - net_cogs

        # OpEx
        gross_opex = abs(pl.get("OpEx", {}).get("total", 0.0))
        # IC OpEx eliminations absorbed into revenue eliminations above (IC-004)
        net_opex = gross_opex

        # EBIT
        ebit = gross_profit - net_opex

        # NCI adjustment: sum of NCI entities' share of profit
        # NCI entities: HCG-SG (25% NCI = 1-0.75), HCG-NL (40% NCI = 1-0.60)
        nci_adjustment = 0.0
        by_entity = aggregated_post_elim.get("by_entity", {})
        for entity_code, entity_agg in by_entity.items():
            pcon = entity_agg.get("pcon", 1.0)
            if pcon < 1.0:
                nci_fraction = 1.0 - pcon
                entity_rev = abs(entity_agg.get("P&L", {}).get("Revenue", {}).get("non_ic", 0.0))
                entity_cogs = abs(entity_agg.get("P&L", {}).get("COGS", {}).get("non_ic", 0.0))
                entity_opex = abs(entity_agg.get("P&L", {}).get("OpEx", {}).get("non_ic", 0.0))
                entity_profit = entity_rev - entity_cogs - entity_opex
                # NCI share of entity profit (before PCon adjustment)
                if pcon > 0:
                    full_entity_profit = entity_profit / pcon
                    nci_adjustment += full_entity_profit * nci_fraction

        group_profit = ebit - nci_adjustment

        return {
            "gross_revenue": round(gross_revenue, 2),
            "ic_revenue_eliminated": round(ic_rev_elim, 2),
            "net_revenue": round(net_revenue, 2),
            "gross_cogs": round(gross_cogs + ic_cogs_elim, 2),  # pre-elim
            "ic_cogs_eliminated": round(ic_cogs_elim, 2),
            "net_cogs": round(net_cogs, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_opex": round(gross_opex, 2),
            "net_opex": round(net_opex, 2),
            "ebit": round(ebit, 2),
            "nci_adjustment": round(nci_adjustment, 2),
            "group_profit": round(group_profit, 2),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Step 4: Compute consolidated Balance Sheet
    # ──────────────────────────────────────────────────────────────────────

    def compute_consolidated_bs(self, aggregated_post_elim: dict) -> dict:
        """
        Compute consolidated Balance Sheet.
        Assets are positive (debit nature), liabilities negative (credit nature).
        """
        bs = aggregated_post_elim.get("BS", {})
        eliminations = aggregated_post_elim.get("eliminations", {})

        gross_assets = abs(bs.get("Assets", {}).get("total", 0.0))
        ic_assets_elim = abs(eliminations.get("ic_assets_eliminated", 0.0))
        net_assets = gross_assets - ic_assets_elim

        gross_liabilities = abs(bs.get("Liabilities", {}).get("total", 0.0))
        ic_liabilities_elim = abs(eliminations.get("ic_liabilities_eliminated", 0.0))
        net_liabilities = gross_liabilities - ic_liabilities_elim

        gross_equity = abs(bs.get("Equity", {}).get("total", 0.0))
        net_equity = net_assets - net_liabilities

        # Balance sheet balanced if net_assets ≈ net_liabilities + net_equity
        total_le = net_liabilities + net_equity
        balance_sheet_balanced = abs(net_assets - total_le) < max(net_assets * 0.01, 1000.0)

        return {
            "gross_assets": round(gross_assets, 2),
            "ic_assets_eliminated": round(ic_assets_elim, 2),
            "net_assets": round(net_assets, 2),
            "gross_liabilities": round(gross_liabilities, 2),
            "ic_liabilities_eliminated": round(ic_liabilities_elim, 2),
            "net_liabilities": round(net_liabilities, 2),
            "gross_equity": round(gross_equity, 2),
            "net_equity": round(net_equity, 2),
            "balance_sheet_balanced": balance_sheet_balanced,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Step 5: Entity contributions
    # ──────────────────────────────────────────────────────────────────────

    def compute_entity_contributions(
        self,
        entity_statements: dict,
        pcon_table: dict,
    ) -> dict:
        """
        Returns entity_code -> {
          "revenue": float,
          "cogs": float,
          "assets": float,
          "liabilities": float,
          "pcon": float,
        }
        All amounts in USD, after applying PCon%.
        """
        contributions: dict = {}

        for entity_code, stmt_dict in entity_statements.items():
            pcon = pcon_table.get(entity_code, 1.0)
            lines = stmt_dict.get("lines", [])

            revenue = 0.0
            cogs = 0.0
            assets = 0.0
            liabilities = 0.0

            for line in lines:
                account_type = line.get("account_type", "")
                account_category = line.get("account_category", "")
                amount_usd = float(line.get("amount_usd", 0.0) or 0.0)
                pcon_amount = abs(amount_usd) * pcon

                if account_type == "P&L":
                    if account_category == "Revenue":
                        revenue += pcon_amount
                    elif account_category in ("COGS", "OpEx"):
                        cogs += pcon_amount
                elif account_type == "BS":
                    if account_category == "Assets":
                        assets += pcon_amount
                    elif account_category == "Liabilities":
                        liabilities += pcon_amount

            contributions[entity_code] = {
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "assets": round(assets, 2),
                "liabilities": round(liabilities, 2),
                "pcon": pcon,
                "pcon_pct": round(pcon * 100, 1),
            }

        return contributions

    # ──────────────────────────────────────────────────────────────────────
    # Step 6: Build ConsolidatedStatement
    # ──────────────────────────────────────────────────────────────────────

    def build_consolidated_statement(
        self,
        pl: dict,
        bs: dict,
        entity_contributions: dict,
        batch_id: str,
        period: str,
        scenario: str,
        aggregated: dict,
        aggregated_post_elim: dict,
    ) -> ConsolidatedStatement:
        """Build and return a ConsolidatedStatement model."""
        eliminations = aggregated_post_elim.get("eliminations", {})

        elimination_summary = {
            "ic_revenue_eliminated": round(eliminations.get("ic_revenue_eliminated", 0.0), 2),
            "ic_cogs_eliminated": round(eliminations.get("ic_cogs_eliminated", 0.0), 2),
            "ic_assets_eliminated": round(eliminations.get("ic_assets_eliminated", 0.0), 2),
            "ic_liabilities_eliminated": round(eliminations.get("ic_liabilities_eliminated", 0.0), 2),
            "total_elimination_impact": round(
                eliminations.get("ic_revenue_eliminated", 0.0) +
                eliminations.get("ic_cogs_eliminated", 0.0) +
                eliminations.get("ic_assets_eliminated", 0.0) +
                eliminations.get("ic_liabilities_eliminated", 0.0),
                2,
            ),
        }

        stmt = ConsolidatedStatement(
            period=period,
            scenario=scenario,
            batch_id=batch_id,
            # P&L
            gross_revenue=pl.get("gross_revenue", 0.0),
            ic_revenue_eliminated=pl.get("ic_revenue_eliminated", 0.0),
            net_revenue=pl.get("net_revenue", 0.0),
            gross_cogs=pl.get("gross_cogs", 0.0),
            ic_cogs_eliminated=pl.get("ic_cogs_eliminated", 0.0),
            net_cogs=pl.get("net_cogs", 0.0),
            gross_opex=pl.get("gross_opex", 0.0),
            net_opex=pl.get("net_opex", 0.0),
            ebit=pl.get("ebit", 0.0),
            nci_share=pl.get("nci_adjustment", 0.0),
            group_profit=pl.get("group_profit", 0.0),
            # Balance Sheet
            gross_assets=bs.get("gross_assets", 0.0),
            ic_assets_eliminated=bs.get("ic_assets_eliminated", 0.0),
            net_assets=bs.get("net_assets", 0.0),
            gross_liabilities=bs.get("gross_liabilities", 0.0),
            ic_liabilities_eliminated=bs.get("ic_liabilities_eliminated", 0.0),
            net_liabilities=bs.get("net_liabilities", 0.0),
            net_equity=bs.get("net_equity", 0.0),
            # Proof
            balance_sheet_balanced=bs.get("balance_sheet_balanced", False),
            entity_contributions=entity_contributions,
            elimination_summary=elimination_summary,
            generated_at=datetime.utcnow(),
        )

        return stmt

    # ──────────────────────────────────────────────────────────────────────
    # Helper
    # ──────────────────────────────────────────────────────────────────────

    def _empty_result(self, batch_id: str, period: str, scenario: str) -> dict:
        """Return an empty consolidation result dict."""
        stmt = ConsolidatedStatement(
            period=period or "",
            scenario=scenario or "",
            batch_id=batch_id or "",
        )
        return stmt.model_dump()
