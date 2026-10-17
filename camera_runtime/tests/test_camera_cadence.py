import unittest

from camera_manager import advance_frame_deadline


class CameraCadenceTests(unittest.TestCase):
    def test_25_fps_source_is_sampled_at_15_fps_average(self):
        interval = 1.0 / 15.0
        next_deadline = 0.0
        accepted = []
        for index in range(25):
            now = index / 25.0
            take, next_deadline = advance_frame_deadline(now, next_deadline, interval)
            if take:
                accepted.append(now)

        self.assertEqual(len(accepted), 15)
        self.assertLessEqual(max(b - a for a, b in zip(accepted, accepted[1:])), 0.081)

    def test_deadline_recovers_without_burst_after_stall(self):
        take, deadline = advance_frame_deadline(1.0, 0.0, 1.0 / 15.0)
        self.assertTrue(take)
        self.assertGreater(deadline, 1.0)
        take_again, _ = advance_frame_deadline(1.001, deadline, 1.0 / 15.0)
        self.assertFalse(take_again)


if __name__ == "__main__":
    unittest.main()
