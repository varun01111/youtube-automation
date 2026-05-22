# YouTube Shorts Daily Uploader

This project uploads YouTube Shorts from a local queue and is designed to work well with Codex automations.

## Overview

The uploader:

- watches the `queue` folder for the next video
- checks that the video looks like a Short candidate
- uploads it with the YouTube Data API
- moves uploaded files to `uploaded`
- saves upload receipts in `receipts`
- keeps a simple upload history in `state/uploads.json`

## Important: bring your own OAuth credentials

This repo does **not** include working Google credentials.

If you want to use this project on your own machine or your own YouTube account, you must create and use:

- your **own** Google Cloud project
- your **own** OAuth desktop client
- your **own** `client_secrets.json`
- your **own** `token.json`

Do not reuse someone else's OAuth client secret or access token.

## Files included in the repo

- `run_daily_upload.py`: main uploader script
- `requirements.txt`: Python dependencies
- `config.example.json`: example configuration
- `README.md`: setup and usage guide

## Files intentionally not published

The repo ignores local/private files such as:

- `secrets/`
- `config.local.json`
- `queue/`
- `uploaded/`
- `failed/`
- `receipts/`
- `state/`

That keeps OAuth secrets, local tokens, queued videos, receipts, and account-specific files out of GitHub.

## Folder layout

- `queue/`: drop new Shorts here
- `uploaded/`: successful uploads are moved here
- `failed/`: optional place for files you want to set aside manually
- `receipts/`: upload result JSON files
- `secrets/`: OAuth client and token files
- `state/`: local upload history

## Requirements

- Python installed
- a Google account that owns or manages the YouTube channel
- access to Google Cloud Console

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Google Cloud setup

### 1. Enable the YouTube Data API

Create or select a Google Cloud project, then enable `YouTube Data API v3`.

### 2. Create an OAuth client

Create an OAuth client with:

- application type: `Desktop app`

Download the JSON file and place it here:

```text
secrets\client_secrets.json
```

The JSON should contain an `installed` section, not `web`.

## Local project setup

Create your local config from the example:

```powershell
Copy-Item config.example.json config.local.json
```

Then edit `config.local.json` as needed.

Useful fields:

- `channel_name`: label used in receipts
- `privacy_status`: `public` or `private`
- `title_template`: fallback title format
- `description_template`: fallback description format
- `default_tags`: fallback tags

## First authorization

Run:

```powershell
python run_daily_upload.py --authorize
```

This opens a Google sign-in page in your browser.

Sign in with the Google account that owns the YouTube channel you want to post to, then approve access.

If successful, the project creates:

```text
secrets\token.json
```

## Switch to a different YouTube account

If you want to post to a new YouTube account later, run:

```powershell
python run_daily_upload.py --reauthorize
```

That deletes the old local token and asks you to sign in again.

## Queue videos

Drop the videos you want to upload into:

```text
queue\
```

The script uploads the oldest queued video first.

## Test before uploading

Dry run:

```powershell
python run_daily_upload.py --dry-run
```

This validates the next queued video and shows the metadata without uploading.

## Upload manually

Basic upload:

```powershell
python run_daily_upload.py
```

Upload a specific file:

```powershell
python run_daily_upload.py --video "queue\my-video.mp4"
```

## Override title, description, and hashtags

You can supply custom metadata for a run:

```powershell
python run_daily_upload.py --title "Amazing hook title" --description "Short description with #shorts" --tags "shorts,viral,trending"
```

This is useful when a Codex automation wants to generate better titles and hashtags for each upload.

## Using with Codex automations

Typical automation flow:

1. Put videos into `queue`
2. Let Codex run `python run_daily_upload.py` on a schedule
3. Codex reports the title, hashtags, source filename, and YouTube video ID

You can create one automation for a morning upload and another for an evening upload.

## Notes

- The current local config can be set to `public` for immediate posting.
- If you want to review uploads before they go live, change `privacy_status` to `private`.
- YouTube generally treats square or vertical videos up to 3 minutes as Shorts.
- Shorts longer than 60 seconds with claimed copyrighted content may be restricted or blocked.

## Security

- Never commit `secrets/client_secrets.json`
- Never commit `secrets/token.json`
- Never commit account passwords or recovery info
- If a client secret or token is exposed, rotate it in Google Cloud and authorize again
