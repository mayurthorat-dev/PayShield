from django.urls import path
from .views import (
    pending_approvals,
    decide_approval,
    approval_history,
    report_cyber_crime,
)

urlpatterns = [
    path("", pending_approvals, name="pending-approvals"),
    path("history/", approval_history, name="approval-history"),
    path(
        "<int:approval_id>/decide/",
        decide_approval,
        name="decide-approval",
    ),
    path(
        "<int:approval_id>/report-fraud/",
        report_cyber_crime,
        name="report-fraud",
    ),
]
