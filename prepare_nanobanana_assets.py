from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("prepare_nanobanana_assets")


@dataclass(slots=True)
class ImageAsset:
    file_name: str
    source_path: str
    input_path: str
    processed_path: str
    prompt_path: str
    page_number: Optional[int]
    asset_type: str
    width: int
    height: int
    caption: str
    prompt: str


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare textbook illustration assets for external redesign workflows.",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        required=True,
        help="Directory with source book illustrations.",
    )
    parser.add_argument(
        "--markdown-path",
        type=Path,
        required=True,
        help="Markdown file used to extract nearby captions for each image.",
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=Path("nanobanana_workspace"),
        help="Workspace where manifests, prompts, and input/output folders will be created.",
    )
    parser.add_argument(
        "--copy-mode",
        choices=("copy", "symlink"),
        default="copy",
        help="Whether to copy source images or create symlinks inside the workspace.",
    )
    return parser.parse_args()


def extract_captions(markdown_text: str) -> dict[str, str]:
    caption_map: dict[str, str] = {}
    lines = markdown_text.splitlines()

    for index, line in enumerate(lines):
        stripped = line.strip()
        if "![](" not in stripped:
            continue

        start = stripped.find("![](")
        end = stripped.find(")", start)
        if end == -1:
            continue

        image_target = stripped[start + 4 : end]
        image_name = Path(image_target).name

        caption = ""
        for next_index in range(index + 1, min(index + 5, len(lines))):
            candidate = lines[next_index].strip()
            if not candidate:
                continue
            if candidate.startswith(("![](", "#", "$$", "|", "```", "<")):
                break
            caption = candidate
            break

        caption_map[image_name] = caption

    return caption_map


def infer_asset_type(image_name: str) -> str:
    lowered = image_name.lower()
    if "figure" in lowered:
        return "figure"
    if "picture" in lowered:
        return "picture"
    return "image"


def infer_page_number(image_name: str) -> Optional[int]:
    marker = "_page_"
    if marker not in image_name:
        return None

    page_fragment = image_name.split(marker, maxsplit=1)[1].split("_", maxsplit=1)[0]
    return int(page_fragment) if page_fragment.isdigit() else None


def build_prompt(asset_type: str, caption: str) -> str:
    base_prompt = (
        "Redesign this textbook illustration in a clean contemporary scientific style. "
        "Preserve the mathematical meaning, labels, geometry, and visual hierarchy. "
        "Keep the background pure white, linework crisp, and typography highly legible. "
        "Do not crop any content. Do not add decorative elements that change the educational meaning."
    )

    type_prompt = {
        "figure": (
            " Favor a vector-like diagram aesthetic suitable for a modern STEM textbook."
        ),
        "picture": (
            " If the source is a scanned physical sketch, convert it into a modern textbook illustration while preserving all annotations."
        ),
        "image": " Keep the result neutral and publication-ready.",
    }[asset_type]

    caption_prompt = f" Caption/context: {caption}" if caption else ""
    return f"{base_prompt}{type_prompt}{caption_prompt}"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def link_or_copy_image(source_path: Path, destination_path: Path, copy_mode: str) -> None:
    if destination_path.exists() or destination_path.is_symlink():
        destination_path.unlink()

    if copy_mode == "symlink":
        destination_path.symlink_to(source_path.resolve())
        return

    shutil.copy2(source_path, destination_path)


def iter_images(images_dir: Path) -> Iterable[Path]:
    supported_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
    for image_path in sorted(images_dir.iterdir()):
        if image_path.is_file() and image_path.suffix.lower() in supported_suffixes:
            yield image_path


def write_manifest(assets: list[ImageAsset], manifest_dir: Path) -> None:
    json_path = manifest_dir / "images_manifest.json"
    csv_path = manifest_dir / "images_manifest.csv"

    json_path.write_text(
        json.dumps([asdict(asset) for asset in assets], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(asdict(assets[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(asset) for asset in assets)


def write_workspace_readme(workspace_dir: Path, asset_count: int) -> None:
    readme_path = workspace_dir / "README.md"
    readme_path.write_text(
        "\n".join(
            [
                "# Nanobanana Image Workspace",
                "",
                f"This workspace contains {asset_count} textbook illustrations prepared for redesign.",
                "",
                "## Folders",
                "",
                "- `input_images/`: source images to upload into the redesign tool.",
                "- `processed_images/`: put redesigned outputs here using the exact same filenames.",
                "- `prompts/`: master prompt and per-image prompts.",
                "- `manifests/`: JSON and CSV metadata for batching and tracking.",
                "",
                "## Recommended workflow",
                "",
                "1. Use `input_images/` as the upload source.",
                "2. Keep the original filenames for redesigned outputs.",
                "3. Save all redesigned files into `processed_images/`.",
                "4. Apply them back into the book with:",
                "   `python3 apply_nanobanana_results.py --processed-dir nanobanana_workspace/processed_images --target-images-dir Output_Final/images`",
                "5. Rebuild the book after image replacement.",
                "",
                "## Quality target",
                "",
                "Preserve mathematical meaning and labels, modernize the visual style, keep white backgrounds, and avoid decorative changes that alter the educational content.",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_arguments()
    images_dir = args.images_dir.expanduser().resolve()
    markdown_path = args.markdown_path.expanduser().resolve()
    workspace_dir = args.workspace_dir.expanduser().resolve()

    if not images_dir.exists():
        raise FileNotFoundError(f"Images directory not found: {images_dir}")
    if not markdown_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {markdown_path}")

    input_dir = ensure_directory(workspace_dir / "input_images")
    processed_dir = ensure_directory(workspace_dir / "processed_images")
    prompt_dir = ensure_directory(workspace_dir / "prompts" / "per_image")
    manifest_dir = ensure_directory(workspace_dir / "manifests")

    markdown_text = markdown_path.read_text(encoding="utf-8")
    caption_map = extract_captions(markdown_text)

    master_prompt = (
        "Redesign educational textbook illustrations for a modern STEM book. "
        "Preserve labels, equations, geometry, and semantic meaning. "
        "Use clean linework, high contrast, a white background, and contemporary textbook typography. "
        "Do not crop or remove educational content."
    )
    ensure_directory(workspace_dir / "prompts").joinpath("master_prompt.txt").write_text(
        f"{master_prompt}\n",
        encoding="utf-8",
    )

    assets: list[ImageAsset] = []
    for image_path in iter_images(images_dir):
        destination_path = input_dir / image_path.name
        link_or_copy_image(image_path, destination_path, args.copy_mode)

        with Image.open(image_path) as img:
            width, height = img.size

        asset_type = infer_asset_type(image_path.name)
        caption = caption_map.get(image_path.name, "")
        prompt = build_prompt(asset_type, caption)
        prompt_path = prompt_dir / f"{image_path.stem}.txt"
        prompt_path.write_text(f"{prompt}\n", encoding="utf-8")

        assets.append(
            ImageAsset(
                file_name=image_path.name,
                source_path=str(image_path),
                input_path=str(destination_path),
                processed_path=str(processed_dir / image_path.name),
                prompt_path=str(prompt_path),
                page_number=infer_page_number(image_path.name),
                asset_type=asset_type,
                width=width,
                height=height,
                caption=caption,
                prompt=prompt,
            )
        )

    if not assets:
        raise RuntimeError(f"No supported images found in {images_dir}")

    write_manifest(assets, manifest_dir)
    write_workspace_readme(workspace_dir, len(assets))

    log.info("Prepared %d images in %s", len(assets), workspace_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
