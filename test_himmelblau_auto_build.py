import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("himmelblau-auto-build.py")
SPEC = importlib.util.spec_from_file_location("himmelblau_auto_build", MODULE_PATH)
auto_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_build)


class ArtifactParsingTests(unittest.TestCase):
    def test_parse_rpm_artifact_detects_distro_for_x86_64(self):
        kind, distro = auto_build.parse_artifact(
            Path("himmelblau-3.2.0-1.x86_64-fedora44.rpm")
        )

        self.assertEqual(kind, "rpm")
        self.assertEqual(distro, "fedora44")

    def test_parse_rpm_artifact_detects_distro_for_aarch64(self):
        kind, distro = auto_build.parse_artifact(
            Path("himmelblau-3.2.0-1.aarch64-rocky10.rpm")
        )

        self.assertEqual(kind, "rpm")
        self.assertEqual(distro, "rocky10")

    def test_collect_from_packaging_buckets_aarch64_rpms_by_distro(self):
        with tempfile.TemporaryDirectory() as tmp:
            packaging = Path(tmp)
            rpm = packaging / "himmelblau-3.2.0-1.aarch64-tumbleweed.rpm"
            rpm.touch()

            _, rpm_map, _ = auto_build.collect_from_packaging(
                packaging, built_since=0
            )

        self.assertEqual(list(rpm_map), ["tumbleweed"])
        self.assertEqual([p.name for p in rpm_map["tumbleweed"]], [rpm.name])

    def test_published_has_pkgs_detects_arm64_rpm_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rpm_dir = base / "rpm" / "fedora44"
            rpm_dir.mkdir(parents=True)
            (rpm_dir / "himmelblau-3.2.0-1.aarch64-fedora44.rpm").touch()

            self.assertTrue(auto_build.published_has_pkgs(base, "arm64-fedora44"))


if __name__ == "__main__":
    unittest.main()
