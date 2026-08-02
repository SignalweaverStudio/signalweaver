\# Lacunar Control Centre — Developer Cheat Sheet



\## Project folder



```powershell

cd C:\\Users\\verti\\Projects\\signalweaver\\lacunar\_mirror\_v0

Activate the virtual environment

.\\.venv\\Scripts\\Activate.ps1

Run all tests

python -m pytest -q

Open the recorder session file

notepad .\\lacunar\_control\\recorder\_session.py

Open the lifecycle file

notepad .\\lacunar\_control\\lifecycle.py

Open the snapshot file

notepad .\\lacunar\_control\\snapshot.py

Open the recorder session tests

notepad .\\tests\\test\_recorder\_session.py

Open this cheat sheet

notepad .\\DEVELOPER\_CHEATSHEET.md

Run the original Lacunar Mirror program

python .\\lacunar\_mirror\_v0.py

Current verified checkpoint

5 tests passing

READY → RECORDING → STOPPING → RECORDED

Immutable snapshots

Backend-owned elapsed time



Then press:



```text

Ctrl + S

