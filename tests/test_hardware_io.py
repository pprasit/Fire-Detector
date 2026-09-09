import threading
import unittest

from fire_detector.hardware_io import (
    HardwareIOQueue,
    PRIORITY_CONTROL,
    PRIORITY_SAFETY,
)


class HardwareIOQueueTests(unittest.TestCase):
    def test_only_bound_owner_executes_hardware_callbacks(self):
        queue = HardwareIOQueue()
        callback_threads = []
        result = []

        caller = threading.Thread(
            target=lambda: result.append(
                queue.call(
                    lambda: callback_threads.append(threading.get_ident()) or "ok",
                    label="test",
                )
            )
        )
        caller.start()
        queue.bind_owner()
        task = queue.take(timeout=0.2)
        self.assertIsNotNone(task)
        queue.execute(task)
        caller.join(0.5)

        self.assertEqual(result, ["ok"])
        self.assertEqual(callback_threads, [threading.get_ident()])
        self.assertTrue(queue.stats()["single_owner"])

    def test_latest_value_supersedes_stale_control_setpoints(self):
        queue = HardwareIOQueue()
        queue.publish_latest("velocity", lambda: "old", label="old")
        queue.publish_latest("velocity", lambda: "new", label="new")
        queue.bind_owner()

        first = queue.take(timeout=0.2)
        second = queue.take(timeout=0.2)
        queue.execute(first)
        queue.execute(second)

        stats = queue.stats()
        self.assertEqual(stats["executed"], 1)
        self.assertEqual(stats["superseded"], 1)

    def test_safety_task_runs_before_control_task(self):
        queue = HardwareIOQueue()
        order = []
        queue.publish_latest(
            "velocity",
            lambda: order.append("control"),
            label="control",
            priority=PRIORITY_CONTROL,
        )
        queue.publish_latest(
            "stop",
            lambda: order.append("stop"),
            label="stop",
            priority=PRIORITY_SAFETY,
        )
        queue.bind_owner()

        queue.execute(queue.take(timeout=0.2))
        queue.execute(queue.take(timeout=0.2))

        self.assertEqual(order, ["stop", "control"])


if __name__ == "__main__":
    unittest.main()
