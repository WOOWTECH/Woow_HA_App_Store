"""Run the credential-free self-tests of the Settings controls harness.

Importing the harness does not open a browser or read credentials; it only
prepares an artifact directory. The self-tests cover the control approval,
mutation and retry policies.
"""
import e2e_settings_controls as controls


def test_settings_controls_policies() -> None:
    controls.assert_self_tests()
