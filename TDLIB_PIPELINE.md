# Native TDLib pipeline

The production entrypoints use `telegram-files`/TDLib for all Telegram work on
all three accounts. Python still owns course grouping, CSV claims, extraction,
pack verification, and rclone upload. Docker and WSL are not required.

## Windows

```powershell
.\setup-tdlib.ps1
.\.venv\Scripts\python.exe tdlib_backend.py start
.\.venv\Scripts\python.exe tdlib_admin.py list
.\.venv\Scripts\python.exe tdlib_admin.py login acc2
.\.venv\Scripts\python.exe tdlib_admin.py login acc3
.\start-multi-pipeline.ps1 -Action Start
```

Use `-Action Status` and `-Action Stop` to inspect or stop only processes
managed by the launcher.

## Ubuntu/VPS

```bash
bash setup.sh
bash start-multi-pipeline.sh start
bash start-multi-pipeline.sh status
bash start-multi-pipeline.sh stop
```

`setup.sh` installs the native dependencies, builds the compatible backend,
and interactively logs in any missing account. It does not use Docker.

## Runtime data

All private/runtime state is under `.runtime/` and is ignored by Git:

- `tdlib/data/`: TDLib account databases and downloaded-file cache.
- `tdlib.env`: backend API configuration.
- `tdlib-accounts.json`: maps `acc1`, `acc2`, and `acc3` to authorized IDs.
- `pipeline-state.json`: managed worker PIDs.

Keep port 8080 bound to localhost. Do not expose the telegram-files API to the
internet because version 0.1.15 has no application-level authentication.

## Architecture

- Acc1 reads the source chat, groups course messages, and assigns each course.
- Acc1 forwards START/file/END batches to the two relay groups through TDLib.
- Acc2 and Acc3 poll their relay history every two seconds and process complete
  batches independently.
- Every worker downloads through TDLib, validates byte size, removes TDLib
  cache, extracts/repackages, verifies Drive packs, uploads through rclone, and
  updates the shared CSV claim atomically.
