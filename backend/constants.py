BASE_URL = "http://localhost:8000"
FILES_ROUTE = "/files"
DB_PATH= "db.sqlite"




parsed_field_name_list = [
    "investor_commitment_amount",
    "management_fee_rate",
    "management_fee_basis",
    "management_fee_billing_cadence",
    "fee_proration_factor",
    "carried_interest_rate",
    "preferred_return_rate",
    "catch_up_rate",
    "organizational_expense_cap",
    "fund_initial_closing_date",
    "fund_final_closing_date",
    "fund_investment_end_date",
    "fund_term_end_date",
    "sub_line_total_payable",
    "sub_line_principal",
    "sub_line_interest",
    "sub_line_fees",
    "sub_line_statement_date",
    "sub_line_repayment_due_date",
    "fund_size_hard_cap",
    "fund_percentage_realized",
    "fund_total_invested_capital",
    "fund_total_realized_capital",
    "fund_total_distributions",
    "fund_total_paid_in_capital",
    "investor_realized_amount",
    "investor_percentage_realized",
    "investor_invested_capital",
    "total_fund_commitment",
    "gp_commitment_amount"
]





emails_and_attachment_fields = [
    {
        "name": "fund_initial_closing_date",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "fund_final_closing_date",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "fund_term_expiration_date",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "investment_period_end_date",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": True,
    },
    # NOTE: capital commitments (investor and fund total) are deliberately NOT
    # extractable fields. A commitment is a contractual term established by the
    # subscription agreement and closings; a capital account statement or
    # realization report only RESTATES it and has no authority to change it.
    # Commitments still change — but via a prescribing document, which the
    # clause interpreter handles (they remain in parsed_field_name_list and the
    # interpreter's field registry). Extracting the restatement wrote redundant
    # timeline segments for an unchanged value, and worse, would let a reported
    # figure silently overwrite the contractual term when the two disagreed.
    # Reconciling and flagging such a disagreement is the right answer; that is
    # not built yet, so the silent-overwrite path is closed instead.
    {
        "name": "gp_commitment_amount",
        "entity_scope": "gp",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "fund_total_realized_capital",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": False,
    },
    {
        "name": "fund_total_distributions",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "fund_total_paid_in_capital",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": False,
    },
    {
        "name": "fund_total_invested_capital",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": False,
    },
    {
        "name": "fund_percentage_realized",
        "entity_scope": "fund",
        "scope_is_semantically_unambiguous": False,
    },
    # investor_commitment_amount intentionally absent — see note above.
    {
        "name": "investor_invested_capital",
        "entity_scope": "investor",
        "scope_is_semantically_unambiguous": False,
    },
    {
        "name": "investor_total_realized_capital",
        "entity_scope": "investor",
        "scope_is_semantically_unambiguous": False,
    },
    {
        "name": "investor_percentage_realized",
        "entity_scope": "investor",
        "scope_is_semantically_unambiguous": False,
    },
    {
        "name": "subscription_line_principal_amount",
        "entity_scope": "subscription_facility",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "subscription_line_fee_amount",
        "entity_scope": "subscription_facility",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "subscription_line_interest_amount",
        "entity_scope": "subscription_facility",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "subscription_line_total_amount",
        "entity_scope": "subscription_facility",
        "scope_is_semantically_unambiguous": True,
    },
    {
        "name": "subscription_line_repayment_due_date",
        "entity_scope": "subscription_facility",
        "scope_is_semantically_unambiguous": True,
    },
]

