# YouTube Shorts Daily Uploader

This folder contains a simple daily YouTube Shorts upload workflow for Codex automations.

## What it does

- Watches `queue` for the next video to upload.
- Validates that the video looks like a Short candidate.
- Uploads it through the official YouTube Data API.
- Writes a receipt JSON file and moves the uploaded file out of the queue.

## Folder layout

- `queue/`: drop new Shorts here
- `uploaded/`: successful uploads are moved here
- `failed/`: validation failures can be moved here manually if needed
- `receipts/`: upload receipts
- `secrets/`: Google OAuth client secrets and token files
- `state/`: local state

## One-time setup

1. Install the Python packages:

```powershell
pip install -r requirements.txt
```

2. Create a Google Cloud OAuth desktop client for the YouTube Data API.

3. Save the OAuth client JSON file as:

```text
secrets\client_secrets.json
```

4. Review and edit:

```text
config.local.json
```

5. Authorize the uploader once:

```powershell
python run_daily_upload.py --authorize
```

If you want to switch to a different YouTube account later:

```powershell
python run_daily_upload.py --reauthorize
```

6. Test with a dry run:

```powershell
python run_daily_upload.py --dry-run
```

## Daily run

```powershell
python run_daily_upload.py
```

You can also override the metadata for a specific upload run:

```powershell
python run_daily_upload.py --title "Your title" --description "Your description #shorts" --tags "shorts,viral,topic"
```

## Notes

- `config.local.json` is currently set to `public`, so scheduled uploads will post immediately to the authorized YouTube account.
- If you want to stage uploads first, change `privacy_status` back to `private`.
- YouTube classifies qualifying square or vertical videos up to 3 minutes as Shorts.
- Shorts longer than 60 seconds with claimed copyrighted content can be blocked.

