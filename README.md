## WP2
This project uses uv for Python package management.
### Environment
Create or sync the virtual environment:
powershell
uv sync
Activate it manually if needed:
powershell
.venv/Scripts/Activate.ps1
### Packages
Add packages to pyproject.toml and update uv.lock:
powershell
uv add requests
Add multiple packages at once:
powershell
uv add requests pandas python-dotenv
Refresh the lock file:
powershell
uv lock 