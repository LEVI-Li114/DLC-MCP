from dlc_mcp.webhook import handle_alarm


class FakeStore:
    def __init__(self):
        self.enqueued = []

    def enqueue_wedata_alert(self, alert_id, payload, task_name, alert_recipient):
        self.enqueued.append((alert_id, payload, task_name, alert_recipient))


def test_handle_alarm_enqueues_and_acknowledges():
    store = FakeStore()
    payload = {"UserName": "on-call", "Content": "任务名称：dwd_demo_di 执行失败"}
    result = handle_alarm(store, payload)
    assert result["status"] == "accepted"
    assert result["alert_id"] == store.enqueued[0][0]
    assert store.enqueued[0][1:] == (payload, "dwd_demo_di", "on-call")


def test_handle_alarm_enqueues_unresolved_alert_too():
    store = FakeStore()
    result = handle_alarm(store, {"Content": "调度异常"})
    assert result["status"] == "accepted"
    assert store.enqueued[0][2] == ""
