# Nanobanana Image Workspace

This workspace contains 177 textbook illustrations prepared for redesign.

## Folders

- `input_images/`: source images to upload into the redesign tool.
- `processed_images/`: put redesigned outputs here using the exact same filenames.
- `prompts/`: master prompt and per-image prompts.
- `manifests/`: JSON and CSV metadata for batching and tracking.

## Recommended workflow

1. Use `input_images/` as the upload source.
2. Keep the original filenames for redesigned outputs.
3. Save all redesigned files into `processed_images/`.
4. Apply them back into the book with:
   `python3 apply_nanobanana_results.py --processed-dir nanobanana_workspace/processed_images --target-images-dir Output_Final/images`
5. Rebuild the book after image replacement.

## Quality target

Preserve mathematical meaning and labels, modernize the visual style, keep white backgrounds, and avoid decorative changes that alter the educational content.