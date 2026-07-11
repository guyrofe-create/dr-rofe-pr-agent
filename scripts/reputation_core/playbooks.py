"""Action plans for each reputation event class."""

PLAYBOOKS = {
    "crisis": {
        "freeze_scheduled_content": True,
        "steps": [
            "Open crisis room and notify executive, communications and legal owners",
            "Build a verified fact timeline; separate facts, claims and unknowns",
            "Prepare a short holding statement without speculation or admissions",
            "Map affected audiences and nominate one spokesperson",
            "Monitor velocity and narrative changes every 15 minutes",
        ],
        "prohibited": ["auto_reply", "delete_evidence", "speculate", "identify_private_people"],
    },
    "rapid_response": {
        "freeze_scheduled_content": True,
        "steps": [
            "Verify source, reach and claim accuracy",
            "Prepare response options: respond, correct privately, or deliberately hold",
            "Obtain executive approval before public action",
            "Measure amplification after action",
        ],
        "prohibited": ["auto_reply", "argue", "threaten"],
    },
    "policy_violation": {
        "freeze_scheduled_content": False,
        "steps": [
            "Preserve URL, timestamp, author and screenshot evidence",
            "Map exact platform policy clauses that may be violated",
            "Prepare a factual report package and manual reporting link",
            "Track decision and one-time appeal deadline",
            "Draft a neutral public response only if silence creates greater risk",
        ],
        "prohibited": ["promise_removal", "mass_report", "retaliate"],
    },
    "review_recovery": {
        "freeze_scheduled_content": False,
        "steps": [
            "Match the review to a real interaction without exposing personal data",
            "Identify the underlying service issue and internal owner",
            "Draft an empathetic, non-defensive response",
            "Move resolution to a private channel",
            "Check whether the review changes after resolution",
        ],
        "prohibited": ["disclose_customer_data", "offer_incentive_for_edit", "argue"],
    },
    "standard_response": {
        "freeze_scheduled_content": False,
        "steps": ["Verify context", "Draft brand-safe response", "Obtain standard approval", "Publish and monitor"],
        "prohibited": ["copy_paste_without_context"],
    },
    "amplify_positive": {
        "freeze_scheduled_content": False,
        "steps": ["Thank the author", "Request permission before reuse", "Add to approved social-proof library"],
        "prohibited": ["reveal_private_details", "fabricate_endorsement"],
    },
}


def get_playbook(name: str) -> dict:
    return PLAYBOOKS.get(name, PLAYBOOKS["standard_response"])
