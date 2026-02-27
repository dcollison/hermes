"""
run_server.py - Launch the Hermes server.

For production use on a build server, run this as a Windows service
using NSSM (https://nssm.cc/):

    nssm install Hermes "C:\Python311\python.exe" "C:\hermes\run_server.py"
    nssm set Hermes AppDirectory "C:\hermes"
    nssm set Hermes AppEnvironmentExtra "PYTHONPATH=C:\hermes"
    nssm start Hermes

Or with a virtual environment:
    nssm install Hermes "C:\hermes\.venv\Scripts\python.exe" "C:\hermes\run_server.py"
"""

import sys
from pathlib import Path

# Ensure the hermes package root is on the path
sys.path.insert(0, str(Path(__file__)))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
    )
