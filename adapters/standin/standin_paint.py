"""The painter behind the stand-in's `image` mode: signed-distance shapes, anti-aliased, lit like clay.

Standard library only. A picture is a stack of layers; each layer is one shape (a function of a point that returns the
signed distance to its outline, negative inside) painted over what is there. Inside a shape the surface is a dome that
rises from the outline over `bulge` units, so every shape gets a light side, a dark side, a darker rim and a highlight
from one light that shines from the top left. Coordinates are "design units" (a 512 unit square, y down, the origin at
the picture's centre); a frame can turn and move a group of layers.
"""
import math
import random

LIGHT = (-0.45, -0.62, 0.64)
_LEN = math.sqrt(sum(c * c for c in LIGHT))
LIGHT = tuple(c / _LEN for c in LIGHT)
_HALF = [LIGHT[0], LIGHT[1], LIGHT[2] + 1.0]
_HLEN = math.sqrt(sum(c * c for c in _HALF))
HALF = tuple(c / _HLEN for c in _HALF)
CEILING = 232  # no painted channel goes above this, so the subject never turns into the white background


def clamp(value, low=0.0, high=1.0):
    return low if value < low else high if value > high else value


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def scale(colour, factor):
    return tuple(c * factor for c in colour)


def smoothstep(low, high, value):
    t = clamp((value - low) / (high - low))
    return t * t * (3 - 2 * t)


# ---- signed distances (negative inside), in design units -------------------------------------------------------

def circle(cx, cy, r):
    return lambda x, y: math.hypot(x - cx, y - cy) - r


def ellipse(cx, cy, rx, ry):
    def sdf(x, y):
        px, py = (x - cx) / rx, (y - cy) / ry
        k0 = math.hypot(px, py)
        k1 = math.hypot(px / rx, py / ry)
        return min(rx, ry) * (k0 - 1) if k1 < 1e-9 else k0 * (k0 - 1) / k1
    return sdf


def rounded_box(cx, cy, hw, hh, r):
    def sdf(x, y):
        qx, qy = abs(x - cx) - hw + r, abs(y - cy) - hh + r
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
    return sdf


def segment(ax, ay, bx, by, ra, rb=None):
    """A capsule from A to B (a cone with round ends when the radii differ)."""
    rb = ra if rb is None else rb
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy or 1e-9

    def sdf(x, y):
        t = clamp(((x - ax) * dx + (y - ay) * dy) / length2)
        return math.hypot(x - ax - t * dx, y - ay - t * dy) - (ra + (rb - ra) * t)
    return sdf


def polygon(points):
    n = len(points)

    def sdf(x, y):
        best, inside = 1e18, False
        j = n - 1
        for i in range(n):
            (xi, yi), (xj, yj) = points[i], points[j]
            ex, ey = xj - xi, yj - yi
            wx, wy = x - xi, y - yi
            t = clamp((wx * ex + wy * ey) / (ex * ex + ey * ey or 1e-9))
            best = min(best, (wx - ex * t) ** 2 + (wy - ey * t) ** 2)
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return -math.sqrt(best) if inside else math.sqrt(best)
    return sdf


def ring(cx, cy, r, width):
    return lambda x, y: abs(math.hypot(x - cx, y - cy) - r) - width


def smooth_union(a, b, k):
    def sdf(x, y):
        da, db = a(x, y), b(x, y)
        h = clamp(0.5 + 0.5 * (db - da) / k)
        return db + (da - db) * h - k * h * (1 - h)
    return sdf


def smooth_subtract(base, cutter, k):
    """BASE with CUTTER bitten out of it, the corner rounded over about K units."""
    def sdf(x, y):
        d2, d1 = base(x, y), cutter(x, y)
        h = clamp(0.5 - 0.5 * (d2 + d1) / k)
        return d2 + (-d1 - d2) * h + k * h * (1 - h)
    return sdf


def union(*shapes):
    return lambda x, y: min(s(x, y) for s in shapes)


def subtract(a, b):
    return lambda x, y: max(a(x, y), -b(x, y))


# ---- a little deterministic noise, for grain and variety --------------------------------------------------------

def _hash(ix, iy, salt):
    h = (ix * 374761393 + iy * 668265263 + salt * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def noise(x, y, salt=0):
    """Smooth value noise in 0..1."""
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(ix, iy, salt), _hash(ix + 1, iy, salt)
    c, d = _hash(ix, iy + 1, salt), _hash(ix + 1, iy + 1, salt)
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy


def dice(digest):
    """A deterministic random source from a 32-byte digest."""
    return random.Random(int.from_bytes(digest[:16], "big"))


# ---- the canvas -----------------------------------------------------------------------------------------------

class Canvas:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.k = min(width, height) / 512.0  # pixels per design unit
        self.rgb = [255.0] * (3 * width * height)
        self.cover = [0.0] * (width * height)  # how much of each pixel is subject (0 = still plain background)
        self.turn, self.shift = 0.0, (0.0, 0.0)

    def frame(self, angle=0.0, dx=0.0, dy=0.0):
        """From now on, layers are drawn in a frame turned by ANGLE (radians) and moved by (DX, DY)."""
        self.turn, self.shift = angle, (dx, dy)

    def frame_about(self, angle, centre):
        """A frame turned by ANGLE that puts the point CENTRE (in the frame) at the middle of the picture."""
        c, s = math.cos(angle), math.sin(angle)
        self.frame(angle, -(c * centre[0] - s * centre[1]), -(s * centre[0] + c * centre[1]))

    def layer(self, sdf, box, albedo, bulge=30.0, spec=0.25, gloss=28.0, rim=0.3, shadow=0.0, glow=0.0):
        """Paint one shape. BOX is (left, top, right, bottom) in the frame; ALBEDO(x, y, depth) gives the colour, where
        depth runs 0 at the outline to 1 at BULGE units inside; a negative BULGE makes a dent. SHADOW darkens what
        is already painted just below and right of the shape; GLOW is light the shape gives off (no shading)."""
        k, w, h = self.k, self.width, self.height
        cx, cy = w / 2.0, h / 2.0
        c, s = math.cos(self.turn), math.sin(self.turn)
        ox, oy = self.shift
        corners = [(c * x - s * y + ox, s * x + c * y + oy) for x in (box[0], box[2]) for y in (box[1], box[3])]
        reach = (6 if shadow else 1) + 1
        x0 = max(0, int(cx + k * (min(p[0] for p in corners) - reach)))
        x1 = min(w, int(cx + k * (max(p[0] for p in corners) + reach)) + 2)
        y0 = max(0, int(cy + k * (min(p[1] for p in corners) - reach)))
        y1 = min(h, int(cy + k * (max(p[1] for p in corners) + reach)) + 2)
        depth_units, dent = abs(bulge), bulge < 0
        eps = 0.6 / k
        sx, sy = 3.5 * shadow, 4.5 * shadow
        rgb, cover = self.rgb, self.cover
        for py in range(y0, y1):
            dy = (py + 0.5 - cy) / k - oy
            for px in range(x0, x1):
                dx = (px + 0.5 - cx) / k - ox
                x, y = c * dx + s * dy, -s * dx + c * dy
                d = sdf(x, y) * k
                index = py * w + px
                if d > 0.75:
                    if shadow and cover[index] > 0:
                        ds = sdf(x - (c * sx + s * sy), y - (-s * sx + c * sy)) * k
                        if ds < 0:
                            f = 1 - 0.34 * shadow * cover[index] * min(1.0, -ds / 2.0)
                            j = index * 3
                            rgb[j], rgb[j + 1], rgb[j + 2] = rgb[j] * f, rgb[j + 1] * f, rgb[j + 2] * f
                    continue
                coverage = clamp(0.5 - d)
                u = clamp(-d / (k * depth_units)) if d < 0 else 0.0
                base = albedo(x, y, u)
                if glow:
                    lit = base
                else:
                    if u >= 1.0:
                        nx = ny = 0.0
                        nz = 1.0
                    else:
                        gx = sdf(x + eps, y) * k - d
                        gy = sdf(x, y + eps) * k - d
                        gl = math.hypot(gx, gy) or 1.0
                        gx, gy = gx / gl, gy / gl
                        gx, gy = c * gx - s * gy, s * gx + c * gy
                        tilt = (1 - u) * 1.5707963
                        st = math.sin(tilt)
                        nz = math.cos(tilt)
                        sign = -1.0 if dent else 1.0
                        nx, ny = gx * st * sign, gy * st * sign
                    diffuse = max(0.0, nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2])
                    shade = 0.36 + 0.82 * diffuse
                    shade *= 1 - rim * (1 - smoothstep(0.0, 0.4, u)) ** 1.5
                    highlight = max(0.0, nx * HALF[0] + ny * HALF[1] + nz * HALF[2]) ** gloss * spec * 255 if spec else 0
                    lit = (base[0] * shade + highlight, base[1] * shade + highlight * 0.96, base[2] * shade + highlight * 0.9)
                j = index * 3
                a = coverage
                rgb[j] += (min(lit[0], CEILING) - rgb[j]) * a
                rgb[j + 1] += (min(lit[1], CEILING) - rgb[j + 1]) * a
                rgb[j + 2] += (min(lit[2], CEILING) - rgb[j + 2]) * a
                cover[index] += a * (1 - cover[index])

    def rows(self):
        """The finished picture as rows of RGB bytes."""
        w = self.width
        return [bytes(int(min(255.0, max(0.0, v)) + 0.5) for v in self.rgb[y * w * 3:(y + 1) * w * 3])
                for y in range(self.height)]


def flat(colour):
    """An albedo of one colour."""
    return lambda x, y, u: colour
