import pymupdf, sys
doc = pymupdf.open(sys.argv[1])
print("pages:", doc.page_count)
for pno in (0, 29, 200, 427):
    page = doc[pno]
    imgs = page.get_images(full=True)
    r = page.rect
    line = [f"p{pno+1} rect={r.width:.0f}x{r.height:.0f}pt imgs={len(imgs)}"]
    for x in imgs:
        info = doc.extract_image(x[0])
        dpi_x = info["width"] / (r.width / 72)
        dpi_y = info["height"] / (r.height / 72)
        line.append(f"  {info['width']}x{info['height']} {info['ext']} cs={info['colorspace']} ~{dpi_x:.0f}x{dpi_y:.0f}dpi bytes={len(info['image'])}")
    print("\n".join(line))
