"""Static checks that the devbox templates keep their secure defaults (AUD-9752, AUD-9753)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESCALATING = {"apt-get", "apt", "dpkg", "usermod", "groupadd", "docker", "su", "sh", "bash", "ALL"}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def sudoers_commands(text):
    """Every command named on a NOPASSWD line in the text."""
    found = []
    for line in re.findall(r"NOPASSWD:\s*([^\"\n>]+)", text):
        for cmd in line.split(","):
            cmd = cmd.strip().strip('"\\ ')
            if cmd and not cmd.startswith("$"):
                found.append(cmd)
    return found


class PortBinding(unittest.TestCase):
    def test_published_ports_bind_loopback_by_default(self):
        ports = re.findall(r'^\s*- "(.*?:\d+:\d+)"', read("assets/docker-compose.yml"), re.M)
        self.assertEqual(len(ports), 2, ports)
        for p in ports:
            self.assertTrue(p.startswith("${DEVBOX_BIND:-127.0.0.1}:"), p)

    def test_env_example_documents_bind_with_loopback_default(self):
        self.assertRegex(read("assets/env.example"), r"(?m)^#?\s*DEVBOX_BIND=127\.0\.0\.1$")


class Password(unittest.TestCase):
    def test_compose_requires_a_password(self):
        self.assertRegex(read("assets/docker-compose.yml"), r"PASSWORD: \$\{DEVBOX_PASSWORD:\?")

    def test_env_example_ships_no_default_password(self):
        text = read("assets/env.example")
        self.assertNotIn("change-me", text)
        self.assertRegex(text, r"(?m)^DEVBOX_PASSWORD=$")

    def test_entrypoint_refuses_empty_and_placeholder_password(self):
        text = read("assets/entrypoint.sh")
        self.assertIn("change-me", text)
        self.assertIn("refusing to start", text)


class Sudoers(unittest.TestCase):
    def test_no_escalating_command_is_granted_by_default(self):
        for rel in ("assets/Dockerfile", "references/toolchain.md"):
            for cmd in sudoers_commands(read(rel)):
                self.assertNotIn(Path(cmd).name, ESCALATING, f"{rel}: {cmd}")

    def test_only_the_wrapper_is_granted(self):
        cmds = sudoers_commands(read("assets/Dockerfile"))
        self.assertIn("/usr/local/bin/devbox-docker-group", cmds)

    def test_entrypoint_uses_no_raw_usermod_or_groupadd(self):
        self.assertNotRegex(read("assets/entrypoint.sh"), r"sudo (usermod|groupadd)")

    def test_docs_do_not_claim_a_limited_list(self):
        for rel in ("references/security.md", "README.md"):
            text = read(rel)
            self.assertNotIn("Every other command asks for a password", text, rel)
            self.assertNotIn("for a fixed list of commands (the package manager", text, rel)


if __name__ == "__main__":
    unittest.main()
