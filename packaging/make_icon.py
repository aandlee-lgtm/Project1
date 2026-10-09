"""Draw the PhotoSelect app icon (1024 px PNG): a sail inside focus brackets."""
import sys
from PIL import Image, ImageDraw, ImageFilter

S = 1024


def draw(path):
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    # macOS icon grid: ~824 px rounded square centred, with a soft shadow.
    shadow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((100, 112, 924, 936), 185, fill=(0, 0, 0, 120))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    body = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    grad = Image.new('RGBA', (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.line([(0, y), (S, y)], fill=(int(24 + 10 * t), int(33 + 14 * t), int(38 + 16 * t), 255))
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((100, 100, 924, 924), 185, fill=255)
    body.paste(grad, (0, 0), mask)
    im.alpha_composite(body)
    d = ImageDraw.Draw(im)
    mint = (173, 225, 197, 255)
    # focus brackets
    w, a, b = 30, 250, 774
    arm = 120
    for x, y, dx, dy in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)):
        d.line([(x, y), (x + dx * arm, y)], fill=mint, width=w)
        d.line([(x, y), (x, y + dy * arm)], fill=mint, width=w)
    # sail and hull
    d.polygon([(520, 300), (520, 640), (690, 640)], fill=(237, 242, 245, 255))
    d.polygon([(495, 340), (495, 640), (360, 640)], fill=mint)
    d.polygon([(340, 668), (700, 668), (650, 718), (390, 718)], fill=(237, 242, 245, 255))
    im.save(path)


if __name__ == '__main__':
    draw(sys.argv[1] if len(sys.argv) > 1 else 'icon-1024.png')
