"""Native vault checks use a unique disposable entry, never a user's account."""

import os
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from claude_provider_switcher.credentials import SystemVault


class NativeCredentialTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager integration")
    def test_windows_credential_roundtrip(self):
        vault = SystemVault()
        service = "claude-provider-switcher:test:" + uuid.uuid4().hex
        self.addCleanup(vault.delete, service)
        self.assertTrue(vault.set(service, "sk-disposable-test-value"))
        self.assertEqual(vault.get(service), "sk-disposable-test-value")
        self.assertTrue(vault.set(service, "sk-disposable-updated"))
        self.assertEqual(vault.get(service), "sk-disposable-updated")
        vault.delete(service)
        self.assertIsNone(vault.get(service))

    @unittest.skipIf(os.name == "nt", "Mock macOS dispatch on POSIX")
    def test_macos_secret_passed_via_stdin_and_checked(self):
        secret = "sk-fake-with-'quote"
        vault = SystemVault()
        with patch.object(sys, "platform", "darwin"), patch("subprocess.run") as run:
            run.side_effect = [
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, secret + "\n", ""),
            ]
            self.assertTrue(vault.set("ccs-test-service", secret))
            self.assertEqual(run.call_args_list[0].args[0], ["security", "-i"])
            self.assertNotIn(secret, str(run.call_args_list[0].args))
            self.assertIn("input", run.call_args_list[0].kwargs)

    @unittest.skipUnless(sys.platform == "darwin" and os.environ.get("CCS_TEST_NATIVE_KEYCHAIN") == "1", "Opt-in macOS Keychain integration")
    def test_macos_keychain_roundtrip(self):
        vault = SystemVault()
        service = "claude-provider-switcher:test:" + uuid.uuid4().hex
        self.addCleanup(vault.delete, service)
        self.assertTrue(vault.set(service, "sk-disposable-test-value"))
        self.assertEqual(vault.get(service), "sk-disposable-test-value")
        vault.delete(service)
        self.assertIsNone(vault.get(service))
