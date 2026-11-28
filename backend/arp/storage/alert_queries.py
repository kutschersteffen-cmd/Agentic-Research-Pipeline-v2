"""Read-only alert log folding helpers shared across monitoring and stewardship."""

from __future__ import annotations

from arp.schemas.portfolio_monitoring import Alert, AlertStatus, AlertTransition
from arp.storage.portfolio_store import PortfolioStore


def _fold_scope_alerts(store: PortfolioStore, scope_id: str) -> dict[str, Alert]:
    """Folds one scope's append-only event log into {alert_id: Alert} with
    each Alert's `status`/`owner` set from the latest `status_changed` row."""
    alerts: dict[str, Alert] = {}
    for row in store.list_alert_events(scope_id):
        if row["event_type"] == "alert_raised":
            alert = Alert.model_validate(row["alert"])
            alerts[alert.alert_id] = alert
        elif row["event_type"] == "status_changed" and row["alert_id"] in alerts:
            transition = AlertTransition.model_validate(row["transition"])
            update = {"status": transition.status}
            if transition.owner:
                update["owner"] = transition.owner
            alerts[row["alert_id"]] = alerts[row["alert_id"]].model_copy(update=update)
    return alerts


def list_alerts(store: PortfolioStore, *, status: AlertStatus | None = None) -> list[Alert]:
    """Every alert across every scope, current status folded in."""
    alerts: list[Alert] = []
    for scope_id in store.list_all_alert_scope_ids():
        alerts.extend(_fold_scope_alerts(store, scope_id).values())
    alerts.sort(key=lambda a: a.triggered_at, reverse=True)
    return [a for a in alerts if status is None or a.status == status]
