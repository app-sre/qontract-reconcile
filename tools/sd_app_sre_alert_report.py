import logging
import re
from collections import defaultdict
from dataclasses import dataclass

QONTRACT_INTEGRATION = "sd-app-sre-alert-report"


@dataclass
class Alert:
    state: str
    message: str
    timestamp: float
    username: str


class AlertStat:
    def __init__(self) -> None:
        self._triggered_alerts = 0
        self._resolved_alerts = 0
        self._elapsed_times: list[float] = []

    def add_triggered(self) -> None:
        self._triggered_alerts += 1

    def add_resolved(self) -> None:
        self._resolved_alerts += 1

    def add_elapsed_time(self, elapsed: float) -> None:
        self._elapsed_times.append(elapsed)

    @property
    def triggered_alerts(self) -> int:
        return self._triggered_alerts

    @property
    def resolved_alerts(self) -> int:
        return self._resolved_alerts

    @property
    def elapsed_times(self) -> list[float]:
        return self._elapsed_times


def group_alerts(messages: list[dict]) -> dict[str, list[Alert]]:
    """Group list of alert messages from Slack in a dict indexed by alert_name"""
    alerts = defaultdict(list)
    for m in messages:
        if "subtype" not in m or m["subtype"] != "bot_message":
            logging.debug(
                f"Skipping message '{m['text']}' as it does not come from a bot"
            )
            continue

        timestamp = float(m["ts"])
        for at in m.get("attachments", []):
            if "title" not in at:
                continue

            mg = re.match(r"Alert: (.*) \[(FIRING:\d+|RESOLVED)\] *(.*)$", at["title"])
            if not mg:
                continue

            alert_name = mg.group(1)
            alert_message = mg.group(3)

            if not alert_name:
                logging.debug(f"no alert name in title {at['title']}. Skipping")
                continue

            # If there's only one alert related to the alert_name, message will be part
            # of the title. If not, alert messages will be part of the text under
            # "Alerts Firing" / "Alerts Resolved"
            if alert_message:
                alert_state = "FIRING" if "FIRING" in mg.group(2) else mg.group(2)
                alerts[alert_name].append(
                    Alert(
                        state=alert_state,
                        message=alert_message,
                        timestamp=timestamp,
                        username=m["username"],
                    )
                )
            else:
                # This may happen for alerts rules without "message". This can happen
                # if schema cannot be validated for a certain alert rule because it
                # is not valid yaml (go templates, jinja templates)
                if "text" not in at:
                    alert_state = "FIRING" if "FIRING" in mg.group(2) else mg.group(2)
                    alerts[alert_name].append(
                        Alert(
                            state=alert_state,
                            message="placeholder",
                            timestamp=timestamp,
                            username=m["username"],
                        )
                    )
                    continue

                alert_state = ""
                for line in at["text"].split("\n"):
                    if "Alerts Firing" in line:
                        alert_state = "FIRING"
                    elif "Alerts Resolved" in line:
                        alert_state = "RESOLVED"
                    elif line.startswith("-"):
                        mg = re.match(r"^- (.+)$", line)
                        if not mg:
                            continue
                        alert_message = mg.group(1)
                        alerts[alert_name].append(
                            Alert(
                                state=alert_state,
                                message=alert_message,
                                timestamp=timestamp,
                                username=m["username"],
                            )
                        )

    return dict(alerts)


def gen_alert_stats(alerts: dict[str, list[Alert]]) -> dict[str, AlertStat]:
    """Get the parsed alerts dict and measure elapsed times until resolved by grouping
    them by alert message and cluster where the message comes from"""
    alert_stats = {}
    for alert_name, alert_list in alerts.items():
        temp = {}
        alert_stats[alert_name] = AlertStat()

        # Slack api returns messages in reversed order, newests first.
        for al in reversed(alert_list):
            key = (al.message, al.username)  # username is different per cluster

            if al.state == "FIRING":
                alert_stats[alert_name].add_triggered()
                temp[key] = al

            if al.state == "RESOLVED":
                alert_stats[alert_name].add_resolved()
                if key in temp:
                    elapsed = al.timestamp - temp[key].timestamp
                    alert_stats[alert_name].add_elapsed_time(elapsed)

    return alert_stats
