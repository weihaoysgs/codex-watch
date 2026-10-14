import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
from PyQt5.QtWidgets import QApplication
from core import Session
from pet import DesktopPet
from pet_scenes import ACTIVITIES, DURATIONS


class PetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pet = DesktopPet()

    def tearDown(self):
        self.pet.close()
        self.pet.deleteLater()
        self.app.processEvents()

    def test_both_pets_have_real_distinct_animation_frames(self):
        for kind in ('cat', 'dog'):
            self.pet.load(kind)
            self.assertFalse(self.pet.error)
            for frames in self.pet.frames.values():
                self.assertGreaterEqual(len(frames), 8)
                images = [f.toImage() for f in frames]
                self.assertTrue(all(not f.isNull() for f in images))
                self.assertTrue(any(im != images[0] for im in images[1:]))

    def test_work_cycles_and_idle_do_not_claim_stale_progress(self):
        session = Session('running', status='running', tracked=True)
        self.pet.sync([session])
        elapsed = 0
        for action, duration in zip(ACTIVITIES, DURATIONS):
            self.assertEqual(self.pet.activity(elapsed+.5)[0], action)
            elapsed += duration
        self.assertEqual(self.pet.activity(elapsed+.5)[0], ACTIVITIES[0])
        self.pet.sync([session], stale=True)
        self.assertEqual(self.pet.activity(1)[0], 'idle')
        self.pet.sync([])
        self.assertEqual(self.pet.activity(1)[0], 'idle')

    def test_every_scene_visibly_animates_for_both_pets(self):
        self.pet.sync([Session('active', status='running', tracked=True)])
        for kind in ('cat', 'dog'):
            self.pet.load(kind)
            elapsed = 0
            for action, duration in zip(ACTIVITIES, DURATIONS):
                self.pet.fixed_time = elapsed + .6
                before = self.pet.grab().toImage()
                self.pet.fixed_time = elapsed + 1.4
                after = self.pet.grab().toImage()
                self.assertNotEqual(before, after, (kind, action))
                elapsed += duration

    def test_preview_is_temporary_and_does_not_forge_task_state(self):
        self.pet.sync([])
        self.pet.preview('snack')
        self.assertEqual(self.pet.activity()[0], 'snack')
        self.assertEqual(self.pet.running, 0)
        self.assertEqual(self.pet.pending, 0)
        self.pet.preview_until = 0
        self.assertEqual(self.pet.activity()[0], 'idle')
        self.pet.preview('laundry')
        self.pet.celebrate()
        self.assertEqual(self.pet.activity()[0], 'celebrate')

    def test_hidden_pet_does_not_run_paint_timer(self):
        self.pet.show()
        self.assertTrue(self.pet.timer.isActive())
        self.pet.hide()
        self.assertFalse(self.pet.timer.isActive())
