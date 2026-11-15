"""(LaküenRecomp) The device profiles: detection, applying, keeping, restoring and the env block (builder/linux/lakuen_profiles.py)"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "builder", "linux"))
import lakuen_profiles as lp  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Profiles(unittest.TestCase):
    def test_every_device_has_a_profile_with_a_title_and_version(self):
        for device in lp.DEVICES:
            p = lp.load(device)
            self.assertTrue(p["title"] and p["version"] >= 1 and p["options"], device)
            self.assertIn("handheld_profile", p["options"], device)

    def test_detect(self):
        with tempfile.TemporaryDirectory() as d:
            dmi, cpu = os.path.join(d, "dmi"), os.path.join(d, "cpuinfo")
            write(os.path.join(dmi, "sys_vendor"), "Valve\n")
            write(os.path.join(dmi, "product_name"), "Galileo\n")
            write(cpu, "model name : AMD Custom APU 0932\n")
            self.assertEqual(lp.detect(dmi, cpu), "steamdeck")
            write(os.path.join(dmi, "sys_vendor"), "LENOVO\n")
            write(os.path.join(dmi, "product_name"), "83L3\n")
            write(cpu, "model name : AMD Ryzen Z2 Go w/ Radeon 680M\n")
            self.assertEqual(lp.detect(dmi, cpu), "legion_go_s")
            write(cpu, "model name : AMD Ryzen 7 5800X3D 8-Core Processor\n")
            write(os.path.join(dmi, "product_name"), "MS-7C02\n")
            self.assertEqual(lp.detect(dmi, cpu), "pc")

    def test_apply_keeps_other_lines_and_restore_puts_them_back(self):
        with tempfile.TemporaryDirectory() as folder:
            opt, env = os.path.join(folder, lp.OPTIONS), os.path.join(folder, lp.ENV)
            write(opt, "volume=80\nresolution=0\nhandheld_profile=0\nresolution=1\npad_a=3\n")
            write(env, "RX_VK_PARALLEL=2\n")
            p = lp.load("steamdeck")
            p["env"] = {"LAKUEN_SHADOWS": "0"}
            self.assertTrue(lp.needs_prompt(folder, p))
            lp.apply(folder, p)
            text = read(opt)
            self.assertIn("volume=80", text)
            self.assertIn("pad_a=3", text)
            self.assertEqual(text.count("resolution="), 1)
            self.assertIn("resolution=4", text)
            self.assertIn("handheld_profile=1", text)
            self.assertIn("frame_generation=2", text)
            e = read(env)
            self.assertIn("RX_VK_PARALLEL=2", e)
            self.assertIn("LAKUEN_SHADOWS=0", e)
            self.assertFalse(lp.needs_prompt(folder, p))
            p2 = dict(p, version=p["version"] + 1, env={})
            self.assertTrue(lp.needs_prompt(folder, p2))   # (a newer version is offered again)
            lp.apply(folder, p2)
            self.assertNotIn("LAKUEN_SHADOWS", read(env))   # (the builder's block goes with the switches)
            self.assertIn("RX_VK_PARALLEL=2", read(env))
            lp.restore(folder)
            self.assertIn("LAKUEN_SHADOWS=0", read(env))   # (the files as before the last profile)
            self.assertEqual(lp.read_marker(folder)["choice"], "kept")

    def test_restore_takes_away_files_the_profile_made(self):
        with tempfile.TemporaryDirectory() as folder:
            lp.apply(folder, lp.load("pc"))
            self.assertIn("output_res=1920x1080", read(os.path.join(folder, lp.OPTIONS)))
            lp.restore(folder)
            self.assertFalse(os.path.exists(os.path.join(folder, lp.OPTIONS)))

    def test_sync_env_adds_new_switches_and_leaves_the_settings(self):
        """(v0.3.7) A switch added to an applied profile (HOS_NATIVE_ZSTD) is written, the player's settings stay; a kept
        profile, another device or another version is not touched"""
        with tempfile.TemporaryDirectory() as folder:
            opt, env = os.path.join(folder, lp.OPTIONS), os.path.join(folder, lp.ENV)
            p = lp.load("legion_go_s")
            old = dict(p, env={"RX_VK_PARALLEL": "2"})
            lp.apply(folder, old)
            write(opt, read(opt).replace("frame_generation=2", "frame_generation=0"))   # (the player's own choice)
            self.assertIn("HOS_NATIVE_ZSTD", p["env"])
            self.assertTrue(lp.sync_env(folder, p))
            self.assertIn("HOS_NATIVE_ZSTD=1", read(env))
            self.assertIn("frame_generation=0", read(opt))
            self.assertFalse(lp.sync_env(folder, p))   # (nothing new)
            lp.keep(folder, p)
            write(env, "")
            self.assertFalse(lp.sync_env(folder, p))
            self.assertEqual(read(env), "")

    def test_keep_is_remembered_and_another_device_asks_again(self):
        with tempfile.TemporaryDirectory() as folder:
            deck = lp.load("steamdeck")
            lp.keep(folder, deck)
            self.assertFalse(lp.needs_prompt(folder, deck))
            self.assertTrue(lp.needs_prompt(folder, lp.load("legion_go_s")))
            self.assertIn("not applied", lp.status(folder))


if __name__ == "__main__":
    unittest.main()
