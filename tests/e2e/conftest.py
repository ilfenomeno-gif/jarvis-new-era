from tests.e2e.report import E2EReportPlugin


def pytest_configure(config):
    config.pluginmanager.register(E2EReportPlugin(), "jarvis-e2e-report")
