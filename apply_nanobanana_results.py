from __future__ import annotations

import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("apply_nanobanana_results")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply redesigned images back into the book images directory.",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        required=True,
        help="Directory with redesigned images produced externally.",
    )
    parser.add_argument(
        "--target-images-dir",
        type=Path,
        required=True,
        help="Book image directory whose files should be replaced.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Optional backup directory. Defaults to a timestamped sibling folder.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    processed_dir = args.processed_dir.expanduser().resolve()
    target_images_dir = args.target_images_dir.expanduser().resolve()

    if not processed_dir.exists():
        raise FileNotFoundError(f"Processed directory not found: {processed_dir}")
    if not target_images_dir.exists():
        raise FileNotFoundError(f"Target image directory not found: {target_images_dir}")

    if args.backup_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = target_images_dir.parent / f"{target_images_dir.name}_backup_{timestamp}"
    else:
        backup_dir = args.backup_dir.expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)

    applied_count = 0
    for processed_path in sorted(processed_dir.iterdir()):
        if not processed_path.is_file():
            continue

        target_path = target_images_dir / processed_path.name
        if not target_path.exists():
            log.warning("Skipping %s because no matching target file exists", processed_path.name)
            continue

        shutil.copy2(target_path, backup_dir / target_path.name)
        shutil.copy2(processed_path, target_path)
        applied_count += 1

    if applied_count == 0:
        log.warning("No redesigned images were applied.")
    else:
        log.info("Applied %d redesigned images. Backup stored in %s", applied_count, backup_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
