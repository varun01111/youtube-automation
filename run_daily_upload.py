from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent
AUTOMATION_ROOT = PROJECT_ROOT
DEFAULT_CONFIG = AUTOMATION_ROOT / "config.local.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


@dataclass
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: float
    duration_seconds: float


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def ensure_runtime_dirs(config: dict[str, Any]) -> None:
    keys = ["queue_dir", "uploaded_dir", "failed_dir", "receipts_dir"]
    for key in keys:
        resolve_path(config[key]).mkdir(parents=True, exist_ok=True)
    resolve_path(config["state_file"]).parent.mkdir(parents=True, exist_ok=True)
    resolve_path(config["client_secrets_file"]).parent.mkdir(parents=True, exist_ok=True)


def load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {"uploads": []}
    return load_json(state_file)


def add_upload_record(state_file: Path, receipt: dict[str, Any]) -> None:
    state = load_state(state_file)
    uploads = state.setdefault("uploads", [])
    uploads.append(receipt)
    save_json(state_file, state)


def format_template(template: str, *, stem: str, now: datetime) -> str:
    values = {
        "stem": stem,
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%d %H:%M"),
    }
    return template.format(**values).strip()


def next_video(queue_dir: Path, allowed_extensions: list[str]) -> Path | None:
    allowed = {ext.lower() for ext in allowed_extensions}
    candidates = [
        path
        for path in queue_dir.iterdir()
        if path.is_file() and path.suffix.lower() in allowed
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime)
    return candidates[0] if candidates else None


def inspect_video(video_path: Path) -> VideoInfo:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video file: {video_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    capture.release()

    duration = 0.0
    if fps > 0 and frame_count > 0:
        duration = frame_count / fps

    return VideoInfo(
        path=video_path,
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=duration,
    )


def validate_short(video: VideoInfo, rules: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    max_duration = float(rules.get("max_duration_seconds", 180))
    require_vertical_or_square = bool(rules.get("require_vertical_or_square", True))
    warn_if_over_60 = bool(rules.get("warn_if_over_60_seconds", True))

    if video.duration_seconds <= 0:
        warnings.append("Could not determine duration accurately from video metadata.")
    elif video.duration_seconds > max_duration:
        errors.append(
            f"Duration is {video.duration_seconds:.1f}s, which exceeds the configured {max_duration:.0f}s limit."
        )

    if require_vertical_or_square and video.width > video.height:
        errors.append(
            f"Video is horizontal ({video.width}x{video.height}); Shorts should be square or vertical."
        )

    if warn_if_over_60 and video.duration_seconds > 60:
        warnings.append(
            "Video is over 60 seconds. Shorts with claimed copyrighted content over 60 seconds can be blocked."
        )

    return errors, warnings


def import_google_upload_modules() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "Missing Google upload packages. Run `pip install -r requirements.txt` from the project folder."
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, MediaFileUpload


def get_credentials(
    client_secrets_file: Path,
    token_file: Path,
    *,
    authorize: bool,
    force_reauthorize: bool = False,
) -> Any:
    Request, Credentials, InstalledAppFlow, _, _ = import_google_upload_modules()

    if force_reauthorize and token_file.exists():
        token_file.unlink()

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if not authorize:
        raise RuntimeError(
            "OAuth token not found or expired. Run `python run_daily_upload.py --authorize` from the project folder first. Use `--reauthorize` to switch YouTube accounts."
        )

    if not client_secrets_file.exists():
        raise RuntimeError(
            f"Missing client secrets file: {client_secrets_file}. Save your Google OAuth desktop client JSON there."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload_video(
    *,
    video_path: Path,
    config: dict[str, Any],
    title: str,
    description: str,
    tags: list[str],
    now: datetime,
) -> dict[str, Any]:
    _, _, _, build, MediaFileUpload = import_google_upload_modules()
    client_secrets_file = resolve_path(config["client_secrets_file"])
    token_file = resolve_path(config["token_file"])
    creds = get_credentials(client_secrets_file, token_file, authorize=False)

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(config.get("category_id", "22")),
        },
        "status": {
            "privacyStatus": config.get("privacy_status", "private"),
            "selfDeclaredMadeForKids": bool(config.get("made_for_kids", False)),
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    return {
        "video_id": response["id"],
        "title": title,
        "privacy_status": body["status"]["privacyStatus"],
        "uploaded_at": now.isoformat(),
    }


def write_receipt(receipts_dir: Path, receipt: dict[str, Any], stem: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    receipt_path = receipts_dir / f"{timestamp}-{stem}.json"
    save_json(receipt_path, receipt)
    return receipt_path


def move_file(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = destination_dir / f"{source.stem}-{timestamp}{source.suffix}"
    shutil.move(str(source), str(destination))
    return destination


def run(
    config_path: Path,
    *,
    dry_run: bool,
    authorize: bool,
    force_reauthorize: bool,
    explicit_video: Path | None,
    explicit_title: str | None,
    explicit_description: str | None,
    explicit_tags: list[str] | None,
) -> int:
    if not config_path.exists():
        raise RuntimeError(f"Config file not found: {config_path}")

    config = load_json(config_path)
    ensure_runtime_dirs(config)

    timezone_name = config.get("timezone", "Asia/Dubai")
    now = datetime.now(ZoneInfo(timezone_name))

    if authorize or force_reauthorize:
        client_secrets_file = resolve_path(config["client_secrets_file"])
        token_file = resolve_path(config["token_file"])
        get_credentials(
            client_secrets_file,
            token_file,
            authorize=True,
            force_reauthorize=force_reauthorize,
        )
        action = "Reauthorization" if force_reauthorize else "Authorization"
        print(f"{action} complete. Token saved to {token_file}")
        return 0

    queue_dir = resolve_path(config["queue_dir"])
    uploaded_dir = resolve_path(config["uploaded_dir"])
    receipts_dir = resolve_path(config["receipts_dir"])
    state_file = resolve_path(config["state_file"])

    video_path = explicit_video or next_video(queue_dir, config.get("allowed_extensions", []))
    if video_path is None:
        print(f"No pending videos found in {queue_dir}")
        return 0

    info = inspect_video(video_path)
    errors, warnings = validate_short(info, config.get("shorts_validation", {}))

    print(
        f"Selected video: {video_path.name} | {info.width}x{info.height} | "
        f"{info.duration_seconds:.1f}s"
    )
    for warning in warnings:
        print(f"Warning: {warning}")
    if errors:
        for error in errors:
            print(f"Error: {error}")
        return 2

    title = (
        explicit_title.strip()
        if explicit_title and explicit_title.strip()
        else format_template(config.get("title_template", "{stem}"), stem=video_path.stem, now=now)
    )
    description = (
        explicit_description.strip()
        if explicit_description and explicit_description.strip()
        else format_template(
        config.get("description_template", "Follow for more shorts.\n\n#shorts"),
        stem=video_path.stem,
        now=now,
    )
    )
    tags = explicit_tags or config.get("default_tags", [])

    if dry_run:
        print("Dry run only. Upload skipped.")
        print(f"Title: {title}")
        print("Description preview:")
        print(description)
        print(f"Tags: {', '.join(tags)}")
        return 0

    receipt = upload_video(
        video_path=video_path,
        config=config,
        title=title,
        description=description,
        tags=tags,
        now=now,
    )
    receipt["source_file"] = str(video_path)
    receipt["channel_name"] = config.get("channel_name", "")
    receipt["video_details"] = {
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "duration_seconds": round(info.duration_seconds, 2),
    }

    receipt_path = write_receipt(receipts_dir, receipt, video_path.stem)
    add_upload_record(state_file, receipt)

    if config.get("move_uploaded_files", True):
        moved_to = move_file(video_path, uploaded_dir)
        receipt["moved_to"] = str(moved_to)
        save_json(receipt_path, receipt)
        print(f"Moved uploaded file to {moved_to}")

    print(f"Upload complete. Video ID: {receipt['video_id']}")
    print(f"Receipt saved to {receipt_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload the next queued YouTube Short.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the uploader config JSON file.",
    )
    parser.add_argument(
        "--authorize",
        action="store_true",
        help="Run the one-time OAuth authorization flow and save token.json.",
    )
    parser.add_argument(
        "--reauthorize",
        action="store_true",
        help="Delete the saved token and authorize again to switch YouTube accounts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the next video and render metadata without uploading.",
    )
    parser.add_argument(
        "--video",
        help="Upload a specific video file instead of automatically picking the next queued file.",
    )
    parser.add_argument(
        "--title",
        help="Override the upload title for this run.",
    )
    parser.add_argument(
        "--description",
        help="Override the upload description for this run.",
    )
    parser.add_argument(
        "--tags",
        help="Comma-separated tags to use for this run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    explicit_video = Path(args.video) if args.video else None
    explicit_tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()] if args.tags else None

    try:
        return run(
            Path(args.config),
            dry_run=args.dry_run,
            authorize=args.authorize,
            force_reauthorize=args.reauthorize,
            explicit_video=explicit_video,
            explicit_title=args.title,
            explicit_description=args.description,
            explicit_tags=explicit_tags,
        )
    except Exception as exc:
        print(f"Uploader failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


