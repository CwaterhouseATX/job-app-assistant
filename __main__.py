"""Run the desktop GUI: python -m job_app_assistant"""

from __future__ import annotations

import sys


def main() -> None:
    from PyQt6.QtWidgets import QApplication

    from job_app_assistant.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SignalMatch")
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
