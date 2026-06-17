"""Unit tests for the secret-redaction gate (PATs, basic-auth URLs, bearer tokens, env-var values)."""
import unittest

from src.shared.utils.redaction import redact


class RedactTests(unittest.TestCase):

    def test_pat_in_clone_url_is_scrubbed_host_kept(self) -> None:
        url = "https://ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE@github.com/pavel-shyrko/JSON-to-CSV.git"
        out = redact(url)
        self.assertNotIn("ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE", out)
        self.assertEqual(out, "https://***@github.com/pavel-shyrko/JSON-to-CSV.git")

    def test_basic_auth_userinfo_is_scrubbed(self) -> None:
        self.assertEqual(redact("https://user:s3cr3tpass@host/x"), "https://***@host/x")

    def test_standalone_github_pat_scrubbed(self) -> None:
        out = redact("token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", out)
        self.assertIn("***", out)

    def test_fine_grained_pat_scrubbed(self) -> None:
        tok = "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
        self.assertNotIn(tok, redact(f"using {tok} now"))

    def test_bearer_and_authorization_header(self) -> None:
        self.assertEqual(redact("Bearer abcdef0123456789"), "Bearer ***")
        self.assertEqual(redact("Authorization: Token xyz12345"), "Authorization: ***")

    def test_extra_secret_exact_value_scrubbed(self) -> None:
        out = redact("client init key=AIzaSyEXAMPLEKEY1234567890", extra_secrets=["AIzaSyEXAMPLEKEY1234567890"])
        self.assertNotIn("AIzaSyEXAMPLEKEY1234567890", out)

    def test_short_extra_secret_ignored(self) -> None:
        # Avoid over-redaction: values shorter than the threshold are not scrubbed.
        self.assertEqual(redact("value=abc", extra_secrets=["abc"]), "value=abc")

    def test_non_secret_text_unchanged(self) -> None:
        s = "Cloned https://github.com/owner/repo.git -> runs/run_x (branch: feat/ticket-T-00)"
        self.assertEqual(redact(s), s)

    def test_idempotent(self) -> None:
        url = "https://ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE@github.com/o/r.git"
        once = redact(url)
        self.assertEqual(redact(once), once)

    def test_empty_is_safe(self) -> None:
        self.assertEqual(redact(""), "")


if __name__ == "__main__":
    unittest.main()
