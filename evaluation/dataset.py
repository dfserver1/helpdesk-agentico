"""
Sample labeled evaluation dataset for the HelpDesk Copilot v12.
These are representative IT helpdesk Q&A pairs.
"""

from evaluation.runner import EvalSample

SAMPLE_DATASET = [
    EvalSample(
        question="How do I reset my Active Directory password?",
        expected_answer="Use the self-service password reset portal or contact your domain administrator.",
        relevant_docs=[
            "password reset portal at https://sspr/",
            "contact domain admin",
        ],
    ),
    EvalSample(
        question="What are the steps to configure Outlook for Office 365?",
        expected_answer="Open Outlook, add your account, use the Office 365 autodiscover settings.",
        relevant_docs=[
            "autodiscover office 365",
            "add account outlook",
        ],
    ),
    EvalSample(
        question="VPN error 800 Windows fix",
        expected_answer="Update GlobalProtect and clear temp files.",
        relevant_docs=[
            "update GlobalProtect",
            "clear temp files",
        ],
    ),
]