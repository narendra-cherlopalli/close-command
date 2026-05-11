"""
All 28 elimination rules for Helios Chemicals Group consolidation.
"""

ELIMINATION_RULES: dict[str, dict] = {
    # ── EQUITY ──────────────────────────────────────────────────────────────
    "EQ-001": {
        "rule_code": "EQ-001",
        "description": "Eliminate investment in subsidiary vs equity of subsidiary",
        "category": "EQUITY",
        "dr_account": "Share Capital & Reserves (Equity)",
        "cr_account": "Investment in Subsidiaries (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "pcon > 50"],
        "nci_applicable": True,
        "formula_description": (
            "Dr Subsidiary Equity at acquisition cost; "
            "Cr Investment in Subsidiary at cost. "
            "NCI share of equity recognised separately."
        ),
    },
    "EQ-002": {
        "rule_code": "EQ-002",
        "description": "Eliminate intercompany dividends declared",
        "category": "EQUITY",
        "dr_account": "Dividend Income (P&L)",
        "cr_account": "Dividends Payable (Liability)",
        "gate_conditions": ["entity_method == GLOBAL", "dividend_declared == True"],
        "nci_applicable": True,
        "formula_description": (
            "Dr Dividend Income in parent P&L; "
            "Cr Dividends Payable in subsidiary. "
            "NCI portion retained in equity."
        ),
    },
    "EQ-003": {
        "rule_code": "EQ-003",
        "description": "Eliminate retained earnings adjustments on consolidation",
        "category": "EQUITY",
        "dr_account": "Retained Earnings (Equity)",
        "cr_account": "Consolidation Adjustment Reserve",
        "gate_conditions": ["entity_method == GLOBAL"],
        "nci_applicable": False,
        "formula_description": (
            "Adjust retained earnings for pre-acquisition profits already "
            "included in investment cost to avoid double-counting."
        ),
    },
    "EQ-004": {
        "rule_code": "EQ-004",
        "description": "Eliminate share premium on consolidation",
        "category": "EQUITY",
        "dr_account": "Share Premium (Equity)",
        "cr_account": "Investment in Subsidiaries (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "share_premium_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr Share Premium account of subsidiary; "
            "Cr Investment cost held by parent. "
            "Eliminates intra-group share premium at acquisition date."
        ),
    },
    "EQ-005": {
        "rule_code": "EQ-005",
        "description": "Eliminate treasury shares held by subsidiary",
        "category": "EQUITY",
        "dr_account": "Treasury Shares (Contra Equity)",
        "cr_account": "Investment in Subsidiaries (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "treasury_shares_held == True"],
        "nci_applicable": False,
        "formula_description": (
            "Where a subsidiary holds shares in the parent, reclassify "
            "as treasury shares at group level and eliminate."
        ),
    },

    # ── INVESTMENT ───────────────────────────────────────────────────────────
    "INV-001": {
        "rule_code": "INV-001",
        "description": "Eliminate intercompany loans (asset side)",
        "category": "INVESTMENT",
        "dr_account": "Intercompany Loan Payable (Liability)",
        "cr_account": "Intercompany Loan Receivable (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "ic_loan_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr IC Loan Payable in borrowing entity; "
            "Cr IC Loan Receivable in lending entity. "
            "Eliminates intra-group financing on the asset side."
        ),
    },
    "INV-002": {
        "rule_code": "INV-002",
        "description": "Eliminate intercompany loans (liability side)",
        "category": "INVESTMENT",
        "dr_account": "Interest Income (P&L)",
        "cr_account": "Interest Expense (P&L)",
        "gate_conditions": ["entity_method == GLOBAL", "ic_loan_interest_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr Interest Income in lending entity P&L; "
            "Cr Interest Expense in borrowing entity P&L. "
            "Eliminates intercompany interest flows."
        ),
    },

    # ── INTERCOMPANY ─────────────────────────────────────────────────────────
    "IC-001": {
        "rule_code": "IC-001",
        "description": "Eliminate IC revenue vs IC cost of sales",
        "category": "INTERCOMPANY",
        "dr_account": "IC Revenue (P&L)",
        "cr_account": "IC Cost of Sales (P&L)",
        "gate_conditions": ["entity_method == GLOBAL", "ic_trade_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr IC Revenue in selling entity; "
            "Cr IC Cost of Sales in buying entity. "
            "Eliminates intra-group trading margin from consolidated P&L."
        ),
    },
    "IC-002": {
        "rule_code": "IC-002",
        "description": "Eliminate IC trade receivables vs payables",
        "category": "INTERCOMPANY",
        "dr_account": "IC Trade Payables (Liability)",
        "cr_account": "IC Trade Receivables (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "ic_trade_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr IC Trade Payable in buying entity; "
            "Cr IC Trade Receivable in selling entity. "
            "Clears intra-group balance sheet positions."
        ),
    },
    "IC-003": {
        "rule_code": "IC-003",
        "description": "Eliminate unrealised profit in inventory",
        "category": "INTERCOMPANY",
        "dr_account": "Cost of Sales (P&L)",
        "cr_account": "Inventory (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "inventory_held_from_ic == True"],
        "nci_applicable": True,
        "formula_description": (
            "Dr Cost of Sales for the unrealised margin; "
            "Cr Inventory to reduce to external cost. "
            "NCI adjustment applied where selling entity is NCI subsidiary."
        ),
    },
    "IC-004": {
        "rule_code": "IC-004",
        "description": "Eliminate IC management fees",
        "category": "INTERCOMPANY",
        "dr_account": "Management Fee Income (P&L)",
        "cr_account": "Management Fee Expense (P&L)",
        "gate_conditions": ["entity_method == GLOBAL", "management_fee_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr Management Fee Income in charging entity; "
            "Cr Management Fee Expense in receiving entity. "
            "Full elimination of intra-group service charges."
        ),
    },
    "IC-005": {
        "rule_code": "IC-005",
        "description": "Eliminate IC royalties",
        "category": "INTERCOMPANY",
        "dr_account": "Royalty Income (P&L)",
        "cr_account": "Royalty Expense (P&L)",
        "gate_conditions": ["entity_method == GLOBAL", "royalty_exists == True"],
        "nci_applicable": False,
        "formula_description": (
            "Dr Royalty Income in licensor entity; "
            "Cr Royalty Expense in licensee entity. "
            "Eliminates intra-group IP charges."
        ),
    },

    # ── GOODWILL ─────────────────────────────────────────────────────────────
    "GW-001": {
        "rule_code": "GW-001",
        "description": "Recognise goodwill on acquisition",
        "category": "GOODWILL",
        "dr_account": "Goodwill (Intangible Asset)",
        "cr_account": "Investment in Subsidiaries (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "acquisition_occurred == True"],
        "nci_applicable": True,
        "formula_description": (
            "Goodwill = Consideration Paid + NCI Fair Value - Fair Value of Net Assets. "
            "Dr Goodwill; Cr Investment account difference at acquisition date."
        ),
    },
    "GW-002": {
        "rule_code": "GW-002",
        "description": "Annual goodwill impairment charge",
        "category": "GOODWILL",
        "dr_account": "Goodwill Impairment (P&L)",
        "cr_account": "Goodwill (Intangible Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "impairment_test_triggered == True"],
        "nci_applicable": False,
        "formula_description": (
            "Impairment = Carrying Amount - Recoverable Amount. "
            "Dr Goodwill Impairment charge to P&L; Cr Goodwill carrying value."
        ),
    },
    "GW-003": {
        "rule_code": "GW-003",
        "description": "Goodwill FX translation adjustment",
        "category": "GOODWILL",
        "dr_account": "Foreign Currency Translation Reserve (Equity)",
        "cr_account": "Goodwill (Intangible Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "foreign_currency_entity == True"],
        "nci_applicable": True,
        "formula_description": (
            "Retranslate goodwill at closing rate each period. "
            "Dr/Cr FCTR in OCI for the exchange difference on goodwill."
        ),
    },
    "GW-004": {
        "rule_code": "GW-004",
        "description": "Goodwill disposal on subsidiary sale",
        "category": "GOODWILL",
        "dr_account": "Gain/Loss on Disposal (P&L)",
        "cr_account": "Goodwill (Intangible Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "subsidiary_disposed == True"],
        "nci_applicable": False,
        "formula_description": (
            "On disposal derecognise remaining goodwill. "
            "Include in the gain or loss on disposal calculation."
        ),
    },

    # ── DIVIDENDS ─────────────────────────────────────────────────────────────
    "DIV-001": {
        "rule_code": "DIV-001",
        "description": "Eliminate wholly-owned subsidiary dividend to parent",
        "category": "DIVIDENDS",
        "dr_account": "Dividend Income (P&L - Parent)",
        "cr_account": "Dividends Declared (Equity - Subsidiary)",
        "gate_conditions": ["entity_method == GLOBAL", "pown == 100", "dividend_declared == True"],
        "nci_applicable": False,
        "formula_description": (
            "100% elimination. Dr Dividend Income in parent; "
            "Cr Dividends Declared in subsidiary retained earnings."
        ),
    },
    "DIV-002": {
        "rule_code": "DIV-002",
        "description": "Eliminate partially-owned subsidiary dividend (NCI share)",
        "category": "DIVIDENDS",
        "dr_account": "NCI in Net Assets (Equity)",
        "cr_account": "Dividends Payable (Liability)",
        "gate_conditions": ["entity_method == GLOBAL", "pown < 100", "dividend_declared == True"],
        "nci_applicable": True,
        "formula_description": (
            "NCI share of dividend reduces NCI balance. "
            "Dr NCI Equity by NCI% of dividend; Cr Dividends Payable."
        ),
    },
    "DIV-003": {
        "rule_code": "DIV-003",
        "description": "Eliminate intercompany interim dividend",
        "category": "DIVIDENDS",
        "dr_account": "Interim Dividend Income (P&L)",
        "cr_account": "Interim Dividends Paid (Equity)",
        "gate_conditions": ["entity_method == GLOBAL", "interim_dividend == True"],
        "nci_applicable": False,
        "formula_description": (
            "Eliminates interim dividend flows during the period. "
            "Dr Interim Dividend Income; Cr Interim Dividends Paid."
        ),
    },
    "DIV-004": {
        "rule_code": "DIV-004",
        "description": "Eliminate proposed but unpaid dividends",
        "category": "DIVIDENDS",
        "dr_account": "Proposed Dividend (Equity)",
        "cr_account": "Dividends Receivable (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "dividend_proposed_not_paid == True"],
        "nci_applicable": False,
        "formula_description": (
            "Where dividend proposed but cash not transferred at period end. "
            "Dr Proposed Dividend; Cr Dividend Receivable in parent."
        ),
    },
    "DIV-005": {
        "rule_code": "DIV-005",
        "description": "Eliminate scrip dividend (bonus issue to parent)",
        "category": "DIVIDENDS",
        "dr_account": "Share Capital (Equity - Subsidiary)",
        "cr_account": "Investment in Subsidiary (Asset - Parent)",
        "gate_conditions": ["entity_method == GLOBAL", "scrip_dividend == True"],
        "nci_applicable": False,
        "formula_description": (
            "Scrip dividend increases subsidiary share capital and parent investment. "
            "Eliminate both sides at group level."
        ),
    },
    "DIV-006": {
        "rule_code": "DIV-006",
        "description": "Eliminate dividend from equity-accounted associate",
        "category": "DIVIDENDS",
        "dr_account": "Dividend Income from Associate (P&L)",
        "cr_account": "Investment in Associate (Asset)",
        "gate_conditions": ["entity_method == EQUITY", "dividend_declared == True"],
        "nci_applicable": False,
        "formula_description": (
            "Under equity method, dividend received reduces carrying value. "
            "Dr Dividend Income; Cr Investment in Associate."
        ),
    },

    # ── STOCK MARGIN ─────────────────────────────────────────────────────────
    "STK-001": {
        "rule_code": "STK-001",
        "description": "Eliminate unrealised margin in closing stock (downstream sale)",
        "category": "STOCK_MARGIN",
        "dr_account": "Cost of Sales (P&L)",
        "cr_account": "Closing Inventory (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "downstream_ic_stock == True"],
        "nci_applicable": False,
        "formula_description": (
            "Downstream: parent sells to subsidiary. Full elimination of margin. "
            "Dr CoS; Cr Inventory by (selling price - cost) * units unsold."
        ),
    },
    "STK-002": {
        "rule_code": "STK-002",
        "description": "Eliminate unrealised margin in closing stock (upstream sale)",
        "category": "STOCK_MARGIN",
        "dr_account": "Cost of Sales (P&L)",
        "cr_account": "Closing Inventory (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "upstream_ic_stock == True"],
        "nci_applicable": True,
        "formula_description": (
            "Upstream: subsidiary sells to parent. NCI share of margin NOT eliminated. "
            "Dr CoS by parent% of margin; Cr Inventory. NCI adjustment in NCI equity."
        ),
    },

    # ── AUC / CAPEX ──────────────────────────────────────────────────────────
    "AUC-001": {
        "rule_code": "AUC-001",
        "description": "Eliminate IC CapEx billing for assets under construction",
        "category": "AUC_CAPEX",
        "dr_account": "IC CapEx Income (P&L)",
        "cr_account": "Assets Under Construction (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "auc_ic_billing == True"],
        "nci_applicable": False,
        "formula_description": (
            "Eliminate profit on IC construction contracts. "
            "Dr IC CapEx Income in contractor entity; Cr AUC in recipient entity."
        ),
    },
    "AUC-002": {
        "rule_code": "AUC-002",
        "description": "Eliminate IC transfer of completed asset from AUC",
        "category": "AUC_CAPEX",
        "dr_account": "IC Asset Transfer Gain (P&L)",
        "cr_account": "Property Plant & Equipment (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "auc_transfer_completed == True"],
        "nci_applicable": False,
        "formula_description": (
            "When AUC transferred at mark-up, eliminate unrealised gain. "
            "Dr IC Transfer Gain; Cr PP&E to bring to cost basis."
        ),
    },
    "AUC-003": {
        "rule_code": "AUC-003",
        "description": "Adjust depreciation on IC asset transfer",
        "category": "AUC_CAPEX",
        "dr_account": "Accumulated Depreciation (Asset)",
        "cr_account": "Depreciation Charge (P&L)",
        "gate_conditions": ["entity_method == GLOBAL", "auc_depreciation_adjustment == True"],
        "nci_applicable": False,
        "formula_description": (
            "Where PP&E was inflated by IC gain, reverse excess depreciation. "
            "Dr Accumulated Depreciation; Cr Depreciation Charge in P&L."
        ),
    },
    "AUC-004": {
        "rule_code": "AUC-004",
        "description": "Eliminate IC progress billing on long-term construction contracts",
        "category": "AUC_CAPEX",
        "dr_account": "Progress Billing Liability (Liability)",
        "cr_account": "Progress Billing Receivable (Asset)",
        "gate_conditions": ["entity_method == GLOBAL", "progress_billing_ic == True"],
        "nci_applicable": False,
        "formula_description": (
            "Eliminate progress billing between group entities on multi-period projects. "
            "Dr Progress Billing Liability; Cr Progress Billing Receivable."
        ),
    },
}

RULE_CATEGORIES: list[str] = [
    "EQUITY",
    "INVESTMENT",
    "INTERCOMPANY",
    "GOODWILL",
    "DIVIDENDS",
    "STOCK_MARGIN",
    "AUC_CAPEX",
]


def get_rule(rule_code: str) -> dict | None:
    """Return rule dict or None if rule_code not found."""
    try:
        return ELIMINATION_RULES.get(rule_code)
    except Exception:
        return None


def get_rules_by_category(category: str) -> list[dict]:
    """Return all rules belonging to a given category."""
    try:
        category_upper = category.upper()
        return [
            rule for rule in ELIMINATION_RULES.values()
            if rule.get("category", "").upper() == category_upper
        ]
    except Exception:
        return []
